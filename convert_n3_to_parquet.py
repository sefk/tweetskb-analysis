#!/usr/bin/env python3
"""Convert TweetSKB N3 gzip files to Parquet format.

For each month_YYYY-MM.n3.gz, produces three Parquet files:
  - month_YYYY-MM_tweets.parquet   (tweet_id, created_at, user_id, likes, shares, positive_emotion, negative_emotion)
  - month_YYYY-MM_entities.parquet (tweet_id, detected_as, matched_uri, confidence)
  - month_YYYY-MM_mentions.parquet (tweet_id, username)

Records are flushed to disk in chunks to keep memory usage bounded.
Logs are written to convert_n3_to_parquet.log in the script directory.
"""

import gzip
import logging
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

# Directories
SCRIPT_DIR = Path(__file__).resolve().parent
SRC_DIR = SCRIPT_DIR / "tweetskb_data"
DST_DIR = SCRIPT_DIR / "tweetskb_ready"
LOG_FILE = SCRIPT_DIR / "convert_n3_to_parquet.log"

# Flush to disk every N tweets parsed (keeps ~200-400 MB per worker)
CHUNK_SIZE = 500_000

# Precompiled regexes for the highly-regular N3 format
RE_TWEET = re.compile(
    r'^_:t(\d+)\s+rdf:type sioc:Post\s*;\s*'
    r'dc:created "([^"]+)"\^\^xsd:dateTime\s*;\s*'
    r'sioc:id "(\d+)"\s*;\s*'
    r'sioc:has_creator _:u([0-9a-f]+)\s*;'
)
RE_LIKE = re.compile(
    r'schema:interactionType schema:LikeAction\s*;\s*'
    r'schema:userInteractionCount "(\d+)"\^\^xsd:integer'
)
RE_SHARE = re.compile(
    r'schema:interactionType schema:ShareAction\s*;\s*'
    r'schema:userInteractionCount "(\d+)"\^\^xsd:integer'
)
RE_POS_EMOTION = re.compile(
    r'onyx:hasEmotionCategory wna:positive-emotion\s*;\s*'
    r'onyx:hasEmotionIntensity "([^"]+)"\^\^xsd:double'
)
RE_NEG_EMOTION = re.compile(
    r'onyx:hasEmotionCategory wna:negative-emotion\s*;\s*'
    r'onyx:hasEmotionIntensity "([^"]+)"\^\^xsd:double'
)
RE_ENTITY = re.compile(
    r'rdf:type nee:Entity\s*;\s*'
    r'nee:detectedAs "([^"]+)"\s*;\s*'
    r'nee:hasMatchedURI <([^>]+)>\s*;\s*'
    r'nee:confidence "([^"]+)"\^\^xsd:double'
)
RE_MENTION = re.compile(
    r'rdf:type sioc:UserAccount\s*;\s*sioc:name "([^"]+)"'
)
RE_SCHEMA_MENTIONS = re.compile(
    r'^_:t(\d+)\s+schema:mentions\s+_:([emh]\d+)'
)

# PyArrow schemas for the three output tables
TWEETS_SCHEMA = pa.schema([
    ("tweet_id", pa.string()),
    ("created_at", pa.timestamp("us")),
    ("user_id", pa.string()),
    ("likes", pa.int32()),
    ("shares", pa.int32()),
    ("positive_emotion", pa.float32()),
    ("negative_emotion", pa.float32()),
])
ENTITIES_SCHEMA = pa.schema([
    ("tweet_id", pa.string()),
    ("detected_as", pa.string()),
    ("matched_uri", pa.string()),
    ("confidence", pa.float32()),
])
MENTIONS_SCHEMA = pa.schema([
    ("tweet_id", pa.string()),
    ("username", pa.string()),
])


def _setup_worker_logging():
    """Configure logging in each worker process (called once per worker)."""
    logger = logging.getLogger("convert")
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(process)d] %(levelname)s %(message)s"
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def _flush_tweets(writer, records):
    """Convert tweet records to an Arrow table and write as a row group."""
    if not records:
        return
    table = pa.table({
        "tweet_id": [r[0] for r in records],
        "created_at": pd.to_datetime([r[1] for r in records]),
        "user_id": [r[2] for r in records],
        "likes": pa.array([r[3] for r in records], type=pa.int32()),
        "shares": pa.array([r[4] for r in records], type=pa.int32()),
        "positive_emotion": pa.array([r[5] for r in records], type=pa.float32()),
        "negative_emotion": pa.array([r[6] for r in records], type=pa.float32()),
    }, schema=TWEETS_SCHEMA)
    writer.write_table(table)


def _flush_entities(writer, records):
    if not records:
        return
    table = pa.table({
        "tweet_id": [r[0] for r in records],
        "detected_as": [r[1] for r in records],
        "matched_uri": [r[2] for r in records],
        "confidence": pa.array([r[3] for r in records], type=pa.float32()),
    }, schema=ENTITIES_SCHEMA)
    writer.write_table(table)


def _flush_mentions(writer, records):
    if not records:
        return
    table = pa.table({
        "tweet_id": [r[0] for r in records],
        "username": [r[1] for r in records],
    }, schema=MENTIONS_SCHEMA)
    writer.write_table(table)


def process_file(args):
    """Parse one .n3.gz file and stream Parquet output in chunks."""
    n3_path, dst_dir, slot_queue = args
    log = _setup_worker_logging()

    stem = n3_path.name.replace(".n3.gz", "")
    tweets_out = dst_dir / f"{stem}_tweets.parquet"
    entities_out = dst_dir / f"{stem}_entities.parquet"
    mentions_out = dst_dir / f"{stem}_mentions.parquet"

    slot = slot_queue.get()

    try:
        if tweets_out.exists() and entities_out.exists() and mentions_out.exists():
            log.info("%s — skipped (already exists)", n3_path.name)
            return {"file": n3_path.name, "status": "skipped"}

        log.info("%s — starting (%.1f MB compressed)", n3_path.name,
                 n3_path.stat().st_size / (1024 ** 2))
        t0 = time.time()

        tweets = []
        entities = []
        mentions = []
        cur_tweet_id = None
        total_tweets = 0
        total_entities = 0
        total_mentions = 0

        file_size = n3_path.stat().st_size
        pbar = tqdm(
            total=file_size, unit="B", unit_scale=True,
            desc=stem, position=slot + 1, leave=False,
        )

        tw_writer = pq.ParquetWriter(tweets_out, TWEETS_SCHEMA)
        ent_writer = pq.ParquetWriter(entities_out, ENTITIES_SCHEMA)
        men_writer = pq.ParquetWriter(mentions_out, MENTIONS_SCHEMA)

        try:
            with open(n3_path, "rb") as raw_f:
                with gzip.open(raw_f, "rt", encoding="utf-8") as f:
                    last_pos = 0
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("@prefix"):
                            continue

                        m = RE_TWEET.match(line)
                        if m:
                            cur_tweet_id = m.group(3)
                            tweets.append((
                                cur_tweet_id, m.group(2), m.group(4),
                                0, 0, 0.0, 0.0,
                            ))
                            if len(tweets) >= CHUNK_SIZE:
                                _flush_tweets(tw_writer, tweets)
                                _flush_entities(ent_writer, entities)
                                _flush_mentions(men_writer, mentions)
                                total_tweets += len(tweets)
                                total_entities += len(entities)
                                total_mentions += len(mentions)
                                log.info("%s — flushed chunk: %d tweets so far",
                                         n3_path.name, total_tweets)
                                tweets.clear()
                                entities.clear()
                                mentions.clear()
                            pos = raw_f.tell()
                            if pos - last_pos >= 1_000_000:
                                pbar.update(pos - pbar.n)
                                last_pos = pos
                            continue

                        m = RE_LIKE.search(line)
                        if m and tweets:
                            t = tweets[-1]
                            tweets[-1] = (t[0], t[1], t[2], int(m.group(1)), t[4], t[5], t[6])
                            continue

                        m = RE_SHARE.search(line)
                        if m and tweets:
                            t = tweets[-1]
                            tweets[-1] = (t[0], t[1], t[2], t[3], int(m.group(1)), t[5], t[6])
                            continue

                        m = RE_POS_EMOTION.search(line)
                        if m and tweets:
                            t = tweets[-1]
                            tweets[-1] = (t[0], t[1], t[2], t[3], t[4], float(m.group(1)), t[6])
                            continue

                        m = RE_NEG_EMOTION.search(line)
                        if m and tweets:
                            t = tweets[-1]
                            tweets[-1] = (t[0], t[1], t[2], t[3], t[4], t[5], float(m.group(1)))
                            continue

                        m = RE_SCHEMA_MENTIONS.match(line)
                        if m:
                            cur_tweet_id = m.group(1)
                            continue

                        m = RE_ENTITY.search(line)
                        if m and cur_tweet_id:
                            entities.append((
                                cur_tweet_id, m.group(1), m.group(2), float(m.group(3)),
                            ))
                            continue

                        m = RE_MENTION.search(line)
                        if m and cur_tweet_id:
                            mentions.append((cur_tweet_id, m.group(1)))
                            continue

            # Flush remaining records
            _flush_tweets(tw_writer, tweets)
            _flush_entities(ent_writer, entities)
            _flush_mentions(men_writer, mentions)
            total_tweets += len(tweets)
            total_entities += len(entities)
            total_mentions += len(mentions)

        finally:
            tw_writer.close()
            ent_writer.close()
            men_writer.close()

        pbar.update(file_size - pbar.n)
        pbar.close()

        elapsed = time.time() - t0
        log.info("%s — done in %.1fs: %d tweets, %d entities, %d mentions",
                 n3_path.name, elapsed, total_tweets, total_entities, total_mentions)
        return {
            "file": n3_path.name,
            "status": "done",
            "tweets": total_tweets,
            "entities": total_entities,
            "mentions": total_mentions,
            "seconds": round(elapsed, 1),
        }
    except Exception:
        log.error("%s — failed:\n%s", n3_path.name, traceback.format_exc())
        raise
    finally:
        slot_queue.put(slot)


def main():
    # Configure logging for the main process
    handler = logging.FileHandler(LOG_FILE)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(process)d] %(levelname)s %(message)s"
    ))
    log = logging.getLogger("convert")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    log.info("=" * 60)
    log.info("Starting conversion run")

    n3_files = sorted(SRC_DIR.glob("month_*.n3.gz"))
    if not n3_files:
        log.error("No .n3.gz files found in %s", SRC_DIR)
        print(f"ERROR: No .n3.gz files found in {SRC_DIR}")
        sys.exit(1)
    log.info("Found %d N3 files in %s", len(n3_files), SRC_DIR)
    print(f"Found {len(n3_files)} N3 files in {SRC_DIR}")

    # Pre-flight space check
    total_compressed = sum(f.stat().st_size for f in n3_files)
    total_compressed_gb = total_compressed / (1024 ** 3)
    estimated_output_gb = total_compressed_gb
    target_real = Path(os.path.realpath(DST_DIR))
    usage = shutil.disk_usage(target_real)
    free_gb = usage.free / (1024 ** 3)
    log.info("Compressed input: %.1f GB, estimated output: %.1f GB, free: %.1f GB on %s",
             total_compressed_gb, estimated_output_gb, free_gb, target_real)
    print(f"Total compressed input: {total_compressed_gb:.1f} GB")
    print(f"Estimated output size:  {estimated_output_gb:.1f} GB")
    print(f"Free space on target:   {free_gb:.1f} GB ({target_real})")

    headroom = estimated_output_gb * 1.1
    if free_gb < headroom:
        log.error("Insufficient space: need %.1f GB but only %.1f GB free", headroom, free_gb)
        print(f"ERROR: Need {headroom:.1f} GB but only {free_gb:.1f} GB free. Aborting.")
        sys.exit(1)

    DST_DIR.mkdir(parents=True, exist_ok=True)

    # Use only performance cores (avoid efficiency cores)
    try:
        max_workers = int(subprocess.check_output(
            ["sysctl", "-n", "hw.perflevel0.logicalcpu"], text=True
        ).strip())
    except Exception:
        max_workers = os.cpu_count()
    log.info("Using %d workers", max_workers)
    print(f"\nProcessing with {max_workers} workers...\n")

    manager = mp.Manager()
    slot_queue = manager.Queue()
    for i in range(max_workers):
        slot_queue.put(i)

    overall = tqdm(total=len(n3_files), desc="Overall", position=0, unit="file")

    errors = []
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(process_file, (f, DST_DIR, slot_queue)): f.name
            for f in n3_files
        }
        for future in as_completed(futures):
            fname = futures[future]
            try:
                result = future.result()
                if result["status"] == "skipped":
                    overall.write(f"  {result['file']} — skipped (already exists)")
                else:
                    overall.write(
                        f"  {result['file']} — "
                        f"{result['tweets']:,} tweets, {result['entities']:,} entities, "
                        f"{result['mentions']:,} mentions ({result['seconds']}s)"
                    )
            except Exception as e:
                errors.append(fname)
                overall.write(f"  {fname} — ERROR: {e}")
            overall.update(1)

    overall.close()

    parquet_files = list(DST_DIR.glob("*.parquet"))
    log.info("Finished. %d parquet files produced. %d errors.", len(parquet_files), len(errors))
    if errors:
        log.error("Failed files: %s", ", ".join(errors))
    print(f"\nDone. {len(parquet_files)} Parquet files in {DST_DIR}")
    if errors:
        print(f"WARNING: {len(errors)} file(s) failed — see {LOG_FILE} for details")
    print(f"Log: {LOG_FILE}")


if __name__ == "__main__":
    main()
