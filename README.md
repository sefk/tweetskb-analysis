# Tweet Analysis

This repo are scripts for processing data from the
[TweetsKB](https://data.gesis.org/tweetskb/) dataset. TweetsKB is a public
large-scale corpus of annotated tweets.

Most of the code was written by Claude.

## Step 1: Download


Run the download script to fetch all files:

```bash
./download_tweetskb.sh [output_dir]   # defaults to ./tweetskb_data
```

The script downloads 115 gzip-compressed N3 RDF files (~3–5 GB each) covering Jan 2013 – Jun 2023. Files already downloaded are skipped, and `wget -c` allows resuming interrupted downloads.

| Parts | Period | Files | Source |
|-------|--------|-------|--------|
| 1–9 | Jan 2013 – Dec 2020 | 97 | zenodo.org |
| 10 | Jan 2021 – Dec 2021 | 12 | doi.org/10.7802/2472 |
| 11 | Jan 2022 – Aug 2022 | 8 | doi.org/10.7802/2473 |
| 12 | Sep 2022 – Jun 2023 | 10 | doi.org/10.7802/2781 |

Parts 10–12 are served via [access.gesis.org](https://access.gesis.org) and are freely accessible without login.

## Step 2: Conversion

Convert the raw N3 RDF files to Parquet for fast analysis with pandas.

```bash
pip install -r requirements.txt
python convert_n3_to_parquet.py
```

The script reads all `month_YYYY-MM.n3.gz` files from `tweetskb_data/` and writes Parquet files to `tweetskb_ready/`. It uses regex-based parsing and processes files in parallel across all CPU cores. Files that have already been converted are skipped, so it is safe to re-run.

For each input file, three Parquet files are produced:

| File | Columns |
|------|---------|
| `month_YYYY-MM_tweets.parquet` | `tweet_id`, `created_at`, `user_id`, `likes`, `shares`, `positive_emotion`, `negative_emotion` |
| `month_YYYY-MM_entities.parquet` | `tweet_id`, `detected_as`, `matched_uri`, `confidence` |
| `month_YYYY-MM_mentions.parquet` | `tweet_id`, `username` |

`
The file layout when done looks like this:
```text
> ls -lh
total 1368
drwxr-xr-x@ 3 sefk  staff    96B Feb 21 10:41 __pycache__
-rw-r--r--@ 1 sefk  staff   584K Feb 21 12:34 convert_n3_to_parquet.log
-rw-r--r--@ 1 sefk  staff    14K Feb 21 10:41 convert_n3_to_parquet.py
-rwxr-xr-x  1 sefk  staff    14K Feb 20 15:12 download_tweetskb.sh
-rw-r--r--@ 1 sefk  staff   1.8K Feb 21 12:48 README.md
-rw-r--r--@ 1 sefk  staff    29B Feb 21 10:07 requirements.txt
lrwxr-xr-x@ 1 sefk  staff    27B Feb 20 16:09 tweetskb_data -> /Volumes/ext1/tweetskb_data
lrwxr-xr-x@ 1 sefk  staff    28B Feb 21 10:31 tweetskb_ready -> /Volumes/ext1/tweetskb_ready
```

Two errors observed during processing:

* Two files weren't processed: `month_2013-03.n3.gz` and `month_2021-05.n3.gz`.
  Errors were during the unzip phase pointing to file truncation or corruption.

* There seems to be a hole in the data, from Dec 2017 through March 2018. No
  file is present at all for February, and the other files are practically
  empty, see below.

```text
month_2017-09.n3.gz — 20,246,552 tweets, 16,804,083 entities, 10,686,799 mentions (319.3s)
month_2017-10.n3.gz — 19,978,891 tweets, 16,545,934 entities, 10,807,113 mentions (315.8s)
month_2017-12.n3.gz — 2 tweets, 12,465,499 entities, 7,686,403 mentions (312.0s)
month_2017-11.n3.gz — 3 tweets, 10,158,202 entities, 6,578,429 mentions (323.4s)
month_2018-02.n3.gz — 5 tweets, 8,113,042 entities, 5,552,449 mentions (299.4s)
month_2018-01.n3.gz — 9 tweets, 11,638,353 entities, 7,621,958 mentions (326.1s)
month_2018-03.n3.gz — 6 tweets, 13,649,117 entities, 9,361,559 mentions (312.7s)
month_2018-04.n3.gz — 18,665,803 tweets, 16,955,536 entities, 14,701,016 mentions (332.2s)
month_2018-05.n3.gz — 19,442,182 tweets, 17,824,912 entities, 15,705,321 mentions (349.9s)
```

## Step 3: Generate Tables

Generate per-date aggregation tables from the per-month Parquet files.

```bash
python agg_date.py [INPUT ...] [-o DIR]
```


```bash
# full dataset — reads tweetskb_ready/, writes tweetskb_tables/date.parquet
python agg_date.py

# custom input directory
python agg_date.py /Volumes/ext1/tweetskb_ready -o /Volumes/ext1/tweetskb_tables

# single month (useful for testing)
python agg_date.py tweetskb_ready/month_2020-03_tweets.parquet -o /tmp/test

# explicit list of months
python agg_date.py tweetskb_ready/month_2020-{01,02,03}_tweets.parquet -o results/
```

The script reads the `_tweets.parquet` and `_mentions.parquet` files from the
input and writes a single `date.parquet` to the output directory. It
processes all months in parallel across performance cores and streams each
month in batches to keep memory usage bounded.

### Script features

**Command-line options.** The positional `INPUT` argument accepts either a
directory (all `month_*_tweets.parquet` files are discovered automatically) or
an explicit list of files (useful for one-month test runs or custom subsets).
`-o / --output` sets the output directory and is created if it does not exist.

| Argument | Default | Description |
|----------|---------|-------------|
| `INPUT` | `tweetskb_ready` | Input directory **or** one or more `_tweets.parquet` files |
| `-o DIR` | `tweetskb_tables` | Output directory; `date.parquet` is written inside it |

**Logging and status reporting.** Every run appends structured log lines to a
`.log` file that lives alongside the script (`agg_date.log`, etc.). Each line
includes a timestamp, PID, and severity level; a `===` separator marks the
start of each invocation. Key events — run start with input/output paths,
per-month progress, any skipped or failed months, and a final summary (row
count, date range, post/like/share totals) — are all captured. `tqdm` shows
two levels of live progress bars: an overall month-level bar at position 0 and
per-worker batch-level bars at positions 1–N, managed via a shared slot queue
so bars never collide. On completion a summary and a 16-row sample are printed
to stdout.

**Multiprocessing.** A `ProcessPoolExecutor` dispatches one month per worker.
Worker count defaults to the number of performance cores
(`sysctl -n hw.perflevel0.logicalcpu` on Apple Silicon, `os.cpu_count()`
elsewhere). Each worker streams its tweets file in 1 M-row batches via
`pq.ParquetFile.iter_batches()`, keeping per-worker peak RAM well under 200 MB
regardless of month size.

**Dirty-word redaction.** After aggregation, all unique entity names are
checked with `better_profanity`. Each flagged entity is replaced with a
deterministic token of the form `[REDACTED_<6-char MD5>]` derived from the
original text. Using a hash rather than a generic placeholder keeps each
dirty entity distinct (preserving the top-100 entity cardinality) and makes
the mapping reproducible across runs. Redacted entities and their tokens are
printed to stdout and logged at INFO level.

### Output schema

The compound primary key is `(year_month, positive_sentiment,
negative_sentiment, has_mentions)`, giving at most 50 rows per month
(5 × 5 × 2 combinations that actually appear in the data).

| Column | Type | Description |
|--------|------|-------------|
| `year_month` | str | `"YYYY-MM"` derived from the source filename |
| `positive_sentiment` | float32 | Quantized intensity: 0.0 \| 0.25 \| 0.5 \| 0.75 \| 1.0 |
| `negative_sentiment` | float32 | Quantized intensity: 0.0 \| 0.25 \| 0.5 \| 0.75 \| 1.0 |
| `has_mentions` | bool | Tweet ID appears in the month's mentions table |
| `total_likes` | int64 | Sum of like counts for the group |
| `total_shares` | int64 | Sum of share counts for the group |
| `post_count` | int64 | Number of tweets in the group |

### Design decisions

**Sentiment granularity.** The `positive_emotion` and `negative_emotion`
values in TweetsKB are already quantized to exactly five discrete levels
(0.0, 0.25, 0.5, 0.75, 1.0) — confirmed by inspecting value distributions
across multiple months spanning the full dataset. These levels are used
directly as dimension values rather than collapsing to a boolean, preserving
meaningful intensity information. A rounding step (`×4 → round → ÷4`) snaps
any floating-point noise to the canonical values before grouping.

**Mentions as a boolean dimension.** Whether a tweet has any mentions is
captured as a `bool` rather than a count, making it practical as a grouping
dimension. The full mention detail remains available in the per-month
`_mentions.parquet` files.

**Performance cores only.** Worker count is set via `sysctl -n
hw.perflevel0.logicalcpu` on macOS (P-cores only on Apple Silicon), falling
back to `os.cpu_count()` elsewhere. Each month is dispatched to a
`ProcessPoolExecutor` worker; results are tiny aggregated frames so
inter-process communication overhead is negligible.

**Streaming batches for memory efficiency.** Each worker reads the tweets
file in 1 M-row batches via `pq.ParquetFile.iter_batches()`, keeping
per-worker RAM well under 200 MB even for the largest months (~20 M tweets).
The mentions set is loaded in one shot (mentions files are much smaller) and
held in a Python `set` for O(1) per-tweet lookup.

**Progress visibility.** `tqdm` shows two levels of bars: an overall
month-level bar at position 0, and per-worker batch-level bars at positions
1–N using a slot queue — the same pattern used in `convert_n3_to_parquet.py`.

