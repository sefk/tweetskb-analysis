#!/usr/bin/env python3
"""
agg_month.py

Reads per-month tweet Parquet files from tweetskb_ready/ and produces a single
aggregated dataset grouped only by sentiment — no entity handling.

Output schema (month.parquet):
  year_month              str      "YYYY-MM"  — primary key component
  positive_sentiment      float32  emotion intensity: 0.0 | 0.25 | 0.5 | 0.75 | 1.0
  negative_sentiment      float32  emotion intensity: 0.0 | 0.25 | 0.5 | 0.75 | 1.0
  total_likes             int64    sum of likes for the group
  total_shares            int64    sum of shares for the group
  post_count              int64    count of tweets in the group

At most 25 rows per month (5 × 5 sentiment levels).  Every tweet in the
tweets file contributes exactly once — there is no entity join and no row
expansion.

Compared with agg_date.py, this script is simpler to run and test: it needs
only the _tweets.parquet files (no _entities.parquet), produces no redacted
or classified columns, and its post_count invariant is exact — the sum equals
the total number of tweets for the month.

Performance & memory:
  - Spawns one worker per performance core (hw.perflevel0.logicalcpu on macOS).
  - Each worker processes one month at a time, streaming tweets in 1M-row
    batches so per-worker peak RSS stays well under 200 MB regardless of
    month size.

Checkpointing:
  - Each completed month is written immediately to {output}/checkpoints_month/YYYY-MM.parquet.
  - On restart, months with existing checkpoints_month are skipped automatically.
  - Pass --no-resume to ignore existing checkpoints_month and reprocess everything.
"""

import argparse
import logging
import math
import multiprocessing as mp
import os
import resource
import signal
import subprocess
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "agg_month.log"

# Rows read from the tweets parquet per batch.  At ~50–70 bytes/row in RAM
# after pandas conversion this keeps each batch under ~70 MB.
BATCH_SIZE = 1_000_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_logging() -> logging.Logger:
    """Configure file logging. Safe to call from both main and worker processes."""
    logger = logging.getLogger("aggregate_month")
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(process)d] %(levelname)s %(message)s"
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def _rss_mb() -> float:
    """Current process RSS in MB. Normalises the platform difference:
    macOS ru_maxrss is bytes; Linux ru_maxrss is kilobytes."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        rss *= 1024   # Linux reports KB
    return rss / (1024 ** 2)


def get_perf_core_count() -> int:
    """Return the number of performance cores.

    On Apple Silicon this queries hw.perflevel0.logicalcpu (P-cores only).
    Falls back to os.cpu_count() on other platforms.
    """
    try:
        n = int(subprocess.check_output(
            ["sysctl", "-n", "hw.perflevel0.logicalcpu"], text=True
        ).strip())
        if n > 0:
            return n
    except Exception:
        pass
    return os.cpu_count() or 1


def discover_jobs(tweets_files: list) -> list:
    """Return sorted (year_month, tweets_path) tuples."""
    jobs = []
    for tf in sorted(tweets_files):
        ym = tf.stem.removeprefix("month_").removesuffix("_tweets")
        jobs.append((ym, tf))
    return jobs


def _checkpoint_path(checkpoint_dir: Path, year_month: str) -> Path:
    return checkpoint_dir / f"{year_month}.parquet"


def _write_checkpoint(rows: list, checkpoint_dir: Path, year_month: str) -> None:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    path = _checkpoint_path(checkpoint_dir, year_month)
    pd.DataFrame(rows).to_parquet(path, index=False)
    logging.getLogger("aggregate_month").info(
        "%s — checkpoint written: %d rows → %s", year_month, len(rows), path
    )


# ---------------------------------------------------------------------------
# Per-worker function (runs in a subprocess)
# ---------------------------------------------------------------------------

def process_month(args: tuple) -> list:
    """Aggregate one month into at most 25 rows (5 × 5 sentiment levels).

    args: (year_month, tweets_path, slot_queue, stop_event)
      slot_queue is a Manager().Queue() that hands out tqdm position slots so
      that per-worker progress bars don't overlap each other or the main bar.
      stop_event is a Manager().Event() set by the main process on SIGINT; the
      worker checks it before each batch and returns [] (no partial results) so
      the month can be safely retried on the next run.

    Every tweet in the tweets file contributes exactly one row to the output
    (unlike agg_date.py, which expands tweets that mention multiple entities).
    The total post_count across all output rows will exactly equal the number
    of tweets in the input file.

    Returns a list of dicts ready to be passed to pd.DataFrame().
    """
    year_month, tweets_path, slot_queue, stop_event = args

    log = _setup_logging()
    slot = slot_queue.get()
    t0 = time.time()

    try:
        log.info("%s — starting", year_month)

        # accum: (pos_val, neg_val) -> [likes_sum, shares_sum, count]
        accum: dict = {}

        pf = pq.ParquetFile(str(tweets_path))
        n_rows = pf.metadata.num_rows
        n_batches = max(1, math.ceil(n_rows / BATCH_SIZE))

        batch_bar = tqdm(
            total=n_batches,
            desc=year_month,
            unit="batch",
            position=slot + 1,   # slot 0 is reserved for the overall bar
            leave=False,
        )

        for batch_num, batch in enumerate(pf.iter_batches(
            batch_size=BATCH_SIZE,
            columns=["tweet_id", "likes", "shares", "positive_emotion", "negative_emotion"],
        )):
            if stop_event.is_set():
                log.warning(
                    "%s — stop requested before batch %d/%d; discarding partial results",
                    year_month, batch_num + 1, n_batches,
                )
                batch_bar.close()
                return []

            df = batch.to_pandas()

            # Sentiment levels: NaN → 0.0, then round to nearest 0.25 to
            # snap any floating-point noise to the canonical quantized values.
            df["positive_sentiment"] = (
                df["positive_emotion"].fillna(0.0).mul(4).round().div(4)
            ).astype("float32")
            df["negative_sentiment"] = (
                df["negative_emotion"].fillna(0.0).mul(4).round().div(4)
            ).astype("float32")

            df["likes"]  = df["likes"].fillna(0).astype("int32")
            df["shares"] = df["shares"].fillna(0).astype("int32")

            for key, grp in df.groupby(
                ["positive_sentiment", "negative_sentiment"],
                observed=True,
            ):
                k = (float(key[0]), float(key[1]))
                if k not in accum:
                    accum[k] = [0, 0, 0]
                accum[k][0] += int(grp["likes"].sum())
                accum[k][1] += int(grp["shares"].sum())
                accum[k][2] += len(grp)

            batch_bar.update(1)

        batch_bar.close()

        # --- Flatten accumulator into row dicts ---
        rows = []
        total_tweets = 0
        for (pos_val, neg_val), (likes, shares, count) in accum.items():
            rows.append({
                "year_month":         year_month,
                "positive_sentiment": pos_val,
                "negative_sentiment": neg_val,
                "total_likes":        likes,
                "total_shares":       shares,
                "post_count":         count,
            })
            total_tweets += count

        elapsed = time.time() - t0
        log.info("%s — done in %.1fs: %d tweets, %d output rows",
                 year_month, elapsed, total_tweets, len(rows))
        return rows

    except Exception:
        log.error("%s — failed:\n%s", year_month, traceback.format_exc())
        raise

    finally:
        slot_queue.put(slot)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate tweetskb_ready tweet Parquet files into a month-level "
                    "sentiment summary (no entity handling)."
    )
    parser.add_argument(
        "input",
        nargs="*",
        default=["tweetskb_ready"],
        metavar="INPUT",
        help="Input directory or one or more _tweets.parquet files "
             "(default: tweetskb_ready)",
    )
    parser.add_argument(
        "-o", "--output",
        default="tweetskb_tables",
        metavar="DIR",
        help="Output directory; month.parquet is written inside it "
             "(default: tweetskb_tables)",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Number of worker processes (default: performance core count). "
             "Use -w 1 to serialize for easier debugging.",
    )
    parser.add_argument(
        "--checkpoint-dir",
        default=None,
        metavar="DIR",
        help="Directory for per-month checkpoint files "
             "(default: {output}/checkpoints_month)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore existing checkpoints_month and reprocess all months.",
    )
    return parser.parse_args()


def resolve_input_files(inputs: list) -> list:
    """Accept a directory or explicit file paths; return a list of tweet Paths."""
    paths = [Path(p) for p in inputs]
    if len(paths) == 1 and paths[0].is_dir():
        return sorted(paths[0].glob("month_*_tweets.parquet"))
    return paths


def main() -> None:
    args = parse_args()
    log = _setup_logging()
    log.info("=" * 60)
    log.info("Starting aggregation run")
    log.info("input=%s  output=%s", args.input, args.output)

    tweets_files = resolve_input_files(args.input)
    if not tweets_files:
        msg = f"No _tweets.parquet files found in {args.input}"
        print(f"ERROR: {msg}", file=sys.stderr)
        log.error(msg)
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "month.parquet"

    checkpoint_dir = (
        Path(args.checkpoint_dir) if args.checkpoint_dir
        else output_dir / "checkpoints_month"
    )

    jobs = discover_jobs(tweets_files)
    if not jobs:
        msg = "No processable months found"
        print(f"ERROR: {msg}", file=sys.stderr)
        log.error(msg)
        sys.exit(1)

    # --- Load existing checkpoints (unless --no-resume) ---
    checkpoint_rows: list = []
    completed_months: set = set()
    if not args.no_resume and checkpoint_dir.exists():
        for cp in sorted(checkpoint_dir.glob("*.parquet")):
            ym = cp.stem
            cp_df = pd.read_parquet(cp)
            checkpoint_rows.extend(cp_df.to_dict("records"))
            completed_months.add(ym)
        if completed_months:
            print(f"Resuming: {len(completed_months)} month(s) already done "
                  f"({min(completed_months)} – {max(completed_months)}).")
            log.info("Resuming: loaded %d checkpoint rows for %d months",
                     len(checkpoint_rows), len(completed_months))

    jobs = [(ym, tf) for ym, tf in jobs if ym not in completed_months]
    if not jobs:
        print("All months already checkpointed. Assembling final output.")
        log.info("All months checkpointed; assembling final output only.")

    n_workers = args.workers or get_perf_core_count()
    if jobs:
        log.info("Found %d months to process, %d workers, batch_size=%d",
                 len(jobs), n_workers, BATCH_SIZE)
        print(f"Found {len(jobs)} month(s) to process. "
              f"{n_workers} worker(s), batch size {BATCH_SIZE:,} rows.")

    # --- Interrupt handling ---
    manager = mp.Manager()
    slot_queue = manager.Queue()
    for i in range(n_workers):
        slot_queue.put(i)
    stop_event = manager.Event()

    def _handle_sigint(sig, frame):
        if not stop_event.is_set():
            print(
                "\nInterrupt received — workers will finish their current batch "
                "then stop. Completed months have been checkpointed.",
                flush=True,
            )
            log.warning("SIGINT received — initiating clean shutdown")
            stop_event.set()

    signal.signal(signal.SIGINT, _handle_sigint)

    # --- Run workers ---
    all_rows: list = list(checkpoint_rows)
    errors: list = []
    overall = tqdm(total=len(jobs), desc="Overall", unit="month", position=0)

    try:
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(process_month, (ym, tf, slot_queue, stop_event)): ym
                for ym, tf in jobs
            }
            for future in as_completed(futures):
                ym = futures[future]
                try:
                    rows = future.result()
                except Exception as exc:
                    errors.append(ym)
                    overall.write(f"  {ym} — ERROR: {exc}")
                    log.error("%s — ERROR: %s", ym, exc)
                else:
                    if rows:
                        all_rows.extend(rows)
                        _write_checkpoint(rows, checkpoint_dir, ym)
                    elif stop_event.is_set():
                        overall.write(f"  {ym} — interrupted, will retry on next run")
                overall.update(1)

                if stop_event.is_set():
                    for f in futures:
                        f.cancel()
                    break
    except KeyboardInterrupt:
        stop_event.set()
        log.warning("KeyboardInterrupt caught in main loop")

    overall.close()

    if stop_event.is_set():
        done = sum(1 for ym, _ in jobs if _checkpoint_path(checkpoint_dir, ym).exists())
        remaining = len(jobs) - done
        print(f"\nStopped early. {done} month(s) checkpointed this run, "
              f"{remaining} remaining. Re-run to continue.")
        log.info("Stopped early. %d checkpointed, %d remaining.", done, remaining)

    if errors:
        msg = f"{len(errors)} month(s) failed: {', '.join(sorted(errors))}"
        print(f"\nWarning: {msg}", file=sys.stderr)
        log.warning(msg)

    if not all_rows:
        print("No data produced.", file=sys.stderr)
        sys.exit(1)

    # --- Build final DataFrame and enforce clean dtypes ---
    df = pd.DataFrame(all_rows)
    df = df.sort_values(
        ["year_month", "positive_sentiment", "negative_sentiment"]
    ).reset_index(drop=True)

    df["positive_sentiment"] = df["positive_sentiment"].astype("float32")
    df["negative_sentiment"] = df["negative_sentiment"].astype("float32")
    df["total_likes"]        = df["total_likes"].astype("int64")
    df["total_shares"]       = df["total_shares"].astype("int64")
    df["post_count"]         = df["post_count"].astype("int64")

    df.to_parquet(output_path, index=False)

    summary = (
        f"{len(df)} rows → {output_path}  |  "
        f"range {df['year_month'].min()}–{df['year_month'].max()}  |  "
        f"{df['post_count'].sum():,} posts  |  "
        f"{df['total_likes'].sum():,} likes  |  "
        f"{df['total_shares'].sum():,} shares"
    )
    log.info("Done. %s", summary)
    if errors:
        log.warning("Failed months: %s", ", ".join(sorted(errors)))

    print(f"\nWrote {len(df)} rows → {output_path}")
    print(f"Year-month range : {df['year_month'].min()} – {df['year_month'].max()}")
    print(f"Total post count : {df['post_count'].sum():,}")
    print(f"Total likes      : {df['total_likes'].sum():,}")
    print(f"Total shares     : {df['total_shares'].sum():,}")
    print(f"Log              : {LOG_FILE}")
    print("\nSample (first 16 rows):")
    print(df.head(16).to_string(index=False))


if __name__ == "__main__":
    main()
