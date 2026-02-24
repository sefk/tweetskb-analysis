#!/usr/bin/env python3
"""
aggregate_tweetskb.py

Reads per-month Parquet files from tweetskb_ready/ and produces a single
aggregated dataset for analysis with pandas and plotly.

Output schema (tweetskb_agg.parquet):
  year_month              str      "YYYY-MM"  — primary key component
  positive_sentiment      float32  emotion intensity: 0.0 | 0.25 | 0.5 | 0.75 | 1.0
  negative_sentiment      float32  emotion intensity: 0.0 | 0.25 | 0.5 | 0.75 | 1.0
  entity                  str      detected entity text (top 100 per month by tweet count)
  total_likes             int64    sum of likes for the group
  total_shares            int64    sum of shares for the group
  post_count              int64    count of (tweet × entity) pairs in the group

The sentiment values are the raw quantized scores from TweetsKB (0.25 = low,
0.5 = medium, 0.75 = high, 1.0 = very high, 0.0 = none detected).  Using the
five discrete levels as a dimension gives at most 5 × 5 × 100 = 2500 rows per
month.  Only tweets that mention at least one top-100 entity are included;
tweets can appear multiple times if they mention more than one top-100 entity.

Performance & memory:
  - Spawns one worker per performance core (hw.perflevel0.logicalcpu on macOS).
  - Each worker processes one month at a time, streaming tweets in 1M-row
    batches so per-worker peak RSS stays well under 200 MB regardless of
    month size.
"""

import argparse
import hashlib
import logging
import math
import multiprocessing as mp
import os
import subprocess
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq
from better_profanity import profanity
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "aggregate_tweetskb.log"

# Rows read from the tweets parquet per batch.  At ~50–70 bytes/row in RAM
# after pandas conversion this keeps each batch under ~70 MB.
BATCH_SIZE = 1_000_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_logging() -> logging.Logger:
    """Configure file logging. Safe to call from both main and worker processes."""
    logger = logging.getLogger("aggregate")
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(process)d] %(levelname)s %(message)s"
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


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
    """Return sorted (year_month, tweets_path, entities_path) tuples."""
    log = logging.getLogger("aggregate")
    jobs = []
    for tf in sorted(tweets_files):
        ym = tf.stem.removeprefix("month_").removesuffix("_tweets")
        ef = tf.parent / tf.name.replace("_tweets.", "_entities.")
        if ef.exists():
            jobs.append((ym, tf, ef))
        else:
            msg = f"no entities file for {ym} — skipping"
            print(f"  Warning: {msg}", file=sys.stderr)
            log.warning(msg)
    return jobs


# ---------------------------------------------------------------------------
# Per-worker function (runs in a subprocess)
# ---------------------------------------------------------------------------

TOP_N_ENTITIES = 100


def process_month(args: tuple) -> list:
    """Aggregate one month into at most 2500 rows (5 × 5 sentiment × 100 entities).

    args: (year_month, tweets_path, entities_path, slot_queue)
      slot_queue is a Manager().Queue() that hands out tqdm position slots so
      that per-worker progress bars don't overlap each other or the main bar.

    Only tweets that mention at least one top-100 entity are included.  A tweet
    that mentions multiple top-100 entities is counted once per entity.

    Returns a list of dicts ready to be passed to pd.DataFrame().
    """
    year_month, tweets_path, entities_path, slot_queue = args

    log = _setup_logging()
    slot = slot_queue.get()
    t0 = time.time()

    try:
        log.info("%s — starting", year_month)

        # --- Find top-N entities for this month by unique tweet count.
        # Load the full entities file, compute counts, then discard everything
        # except the filtered (tweet_id, entity) pairs to free peak memory.
        ent_full = pq.read_table(
            str(entities_path), columns=["tweet_id", "detected_as"]
        ).to_pandas()

        top_entities = (
            ent_full.groupby("detected_as")["tweet_id"]
            .nunique()
            .nlargest(TOP_N_ENTITIES)
            .index
        )

        # Keep one row per (tweet_id, entity); drop duplicates so a tweet
        # that mentions the same entity twice is only counted once.
        ent = (
            ent_full[ent_full["detected_as"].isin(top_entities)]
            [["tweet_id", "detected_as"]]
            .drop_duplicates()
            .rename(columns={"detected_as": "entity"})
        )
        del ent_full

        log.info("%s — top-%d entities found, %d (tweet, entity) pairs",
                 year_month, TOP_N_ENTITIES, len(ent))

        # --- Stream tweets in fixed-size batches and accumulate aggregates.
        # accum: (pos_val, neg_val, entity) -> [likes_sum, shares_sum, count]
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

        for batch in pf.iter_batches(
            batch_size=BATCH_SIZE,
            columns=["tweet_id", "likes", "shares", "positive_emotion", "negative_emotion"],
        ):
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

            # Inner join explodes each tweet into one row per top-100 entity.
            # Tweets with no top-100 entity are dropped by the inner join.
            df = df.merge(ent, on="tweet_id", how="inner")

            for key, grp in df.groupby(
                ["positive_sentiment", "negative_sentiment", "entity"],
                observed=True,
            ):
                k = (float(key[0]), float(key[1]), str(key[2]))
                if k not in accum:
                    accum[k] = [0, 0, 0]
                accum[k][0] += int(grp["likes"].sum())
                accum[k][1] += int(grp["shares"].sum())
                accum[k][2] += len(grp)

            batch_bar.update(1)

        batch_bar.close()

        # --- Flatten accumulator into row dicts ---
        rows = []
        total_pairs = 0
        for (pos_val, neg_val, entity), (likes, shares, count) in accum.items():
            rows.append({
                "year_month":         year_month,
                "positive_sentiment": pos_val,
                "negative_sentiment": neg_val,
                "entity":             entity,
                "total_likes":        likes,
                "total_shares":       shares,
                "post_count":         count,
            })
            total_pairs += count

        elapsed = time.time() - t0
        log.info("%s — done in %.1fs: %d (tweet, entity) pairs, %d output rows",
                 year_month, elapsed, total_pairs, len(rows))
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
        description="Aggregate tweetskb_ready Parquet files into a single analysis dataset."
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
        default="tweetskb_agg",
        metavar="DIR",
        help="Output directory; tweetskb_agg.parquet is written inside it "
             "(default: tweetskb_agg)",
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
    output_path = output_dir / "tweetskb_agg.parquet"

    jobs = discover_jobs(tweets_files)
    if not jobs:
        msg = "No processable month pairs found (missing mentions files?)"
        print(f"ERROR: {msg}", file=sys.stderr)
        log.error(msg)
        sys.exit(1)

    n_workers = get_perf_core_count()
    log.info("Found %d months, %d workers, batch_size=%d", len(jobs), n_workers, BATCH_SIZE)
    print(f"Found {len(jobs)} months. Aggregating with {n_workers} workers "
          f"(batch size: {BATCH_SIZE:,} rows).")

    # Manager queue hands out tqdm position slots (1..n_workers) to workers
    # so their per-batch bars don't collide with the overall bar at position 0.
    manager = mp.Manager()
    slot_queue = manager.Queue()
    for i in range(n_workers):
        slot_queue.put(i)

    all_rows: list = []
    errors: list = []
    overall = tqdm(total=len(jobs), desc="Overall", unit="month", position=0)

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(process_month, (ym, tf, ef, slot_queue)): ym
            for ym, tf, ef in jobs
        }
        for future in as_completed(futures):
            ym = futures[future]
            try:
                all_rows.extend(future.result())
            except Exception as exc:
                errors.append(ym)
                overall.write(f"  {ym} — ERROR: {exc}")
                log.error("%s — ERROR: %s", ym, exc)
            overall.update(1)

    overall.close()

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
        ["year_month", "entity", "positive_sentiment", "negative_sentiment"]
    ).reset_index(drop=True)

    df["positive_sentiment"] = df["positive_sentiment"].astype("float32")
    df["negative_sentiment"] = df["negative_sentiment"].astype("float32")
    df["entity"]             = df["entity"].astype(str)
    df["total_likes"]        = df["total_likes"].astype("int64")
    df["total_shares"]       = df["total_shares"].astype("int64")
    df["post_count"]         = df["post_count"].astype("int64")

    # --- Redact dirty entities ---
    # Check each unique entity once, then replace flagged names with a
    # deterministic redaction token.  Using a short MD5 hash of the original
    # text keeps each dirty entity distinct (preserving the 100-entity count)
    # and makes the mapping reproducible across runs.
    unique_entities = df["entity"].unique()
    dirty = {e for e in unique_entities if profanity.contains_profanity(e)}
    if dirty:
        redaction_map = {
            e: f"[REDACTED_{hashlib.md5(e.encode()).hexdigest()[:6]}]"
            for e in dirty
        }
        df["entity"] = df["entity"].replace(redaction_map)
        log.info("Redacted %d dirty entities: %s",
                 len(dirty), ", ".join(f"{k!r} → {v}" for k, v in redaction_map.items()))
        print(f"Redacted {len(dirty)} dirty entities: "
              + ", ".join(f"{k!r} → {v}" for k, v in redaction_map.items()))

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
