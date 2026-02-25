#!/usr/bin/env python3
"""
e2e_agg_test.py

End-to-end data quality tests comparing agg_date.process_month and
agg_entity.process_month against each other and against raw Parquet files
across multiple months.

EXPENSIVE — runs process_month() twice per test month (once per script).
Do NOT include in the default pytest run:

    pytest agg_date_test.py agg_entity_test.py -v    # fast unit tests only

Run separately:

    pytest e2e_agg_test.py -v
    pytest e2e_agg_test.py -v --months 2013-01 2013-06 2014-01

Test categories:

  Month isolation
    Each script's output rows carry only the correct year_month.

  Cross-script consistency (top-100 entities)
    For entities in agg_date's top-100, the summed date post_count /
    total_likes / total_shares must agree with agg_entity for every test
    month.  Both scripts use the same drop_duplicates logic on
    (tweet_id, entity), so a mismatch indicates an aggregation error.

  "Other" double-count detection
    Identifies tweets that mention both a top-100 entity AND a non-top
    entity.  The agg_date docstring states 'Other' should contain tweets
    mentioning *only* non-top entities.  A failure here means those mixed
    tweets are being counted under both their named entity and 'Other',
    inflating engagement totals in the 'Other' bucket.

  Per-entity raw verification (top-5 entities per month)
    post_count, total_likes, and total_shares for the five highest-volume
    entities each month are verified directly against raw Parquet.
"""

import multiprocessing as mp
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agg_date
import agg_entity

READY_DIR = Path(__file__).resolve().parent / "tweetskb_ready"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_months(pytestconfig):
    """List of year-months to test, from the --months CLI option."""
    return pytestconfig.getoption("months")


@pytest.fixture(scope="session")
def month_raw(test_months):
    """Load raw tweets and entities for each test month.

    Returns dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
        month -> (tweets_df, entities_df)

    Months whose Parquet files are absent are silently omitted.
    """
    data = {}
    for month in test_months:
        tweets_path   = READY_DIR / f"month_{month}_tweets.parquet"
        entities_path = READY_DIR / f"month_{month}_entities.parquet"
        if not tweets_path.exists() or not entities_path.exists():
            continue
        tweets_df = pq.read_table(
            str(tweets_path),
            columns=["tweet_id", "likes", "shares"],
        ).to_pandas()
        tweets_df["likes"]  = tweets_df["likes"].fillna(0).astype("int64")
        tweets_df["shares"] = tweets_df["shares"].fillna(0).astype("int64")
        entities_df = pq.read_table(
            str(entities_path),
            columns=["tweet_id", "detected_as"],
        ).to_pandas()
        data[month] = (tweets_df, entities_df)
    if not data:
        pytest.skip(f"None of the requested months found in {READY_DIR}")
    return data


def _run_process_month(script_module, month_raw):
    """Run script_module.process_month for each month.

    Returns dict[str, pd.DataFrame]: month -> output DataFrame (pre-redaction).
    Each month gets a fresh Manager queue and stop event; the Manager is shut
    down cleanly after all months finish.
    """
    results = {}
    manager = mp.Manager()
    try:
        for month in month_raw:
            tweets_path   = READY_DIR / f"month_{month}_tweets.parquet"
            entities_path = READY_DIR / f"month_{month}_entities.parquet"
            q = manager.Queue()
            q.put(0)
            e = manager.Event()
            rows = script_module.process_month(
                (month, tweets_path, entities_path, q, e)
            )
            results[month] = pd.DataFrame(rows) if rows else pd.DataFrame()
    finally:
        manager.shutdown()
    return results


@pytest.fixture(scope="session")
def month_date_output(month_raw):
    """Run agg_date.process_month for each loaded month (pre-redaction)."""
    return _run_process_month(agg_date, month_raw)


@pytest.fixture(scope="session")
def month_entity_output(month_raw):
    """Run agg_entity.process_month for each loaded month (pre-redaction)."""
    return _run_process_month(agg_entity, month_raw)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _top_date_entities(entities_df):
    """Recompute agg_date's top-N entity set from raw entities_df."""
    return set(
        entities_df.groupby("detected_as")["tweet_id"]
        .nunique()
        .nlargest(agg_date.TOP_N_ENTITIES)
        .index
    )


def _fmt_failures(failures, limit=20):
    lines = "\n".join(failures[:limit])
    if len(failures) > limit:
        lines += f"\n... and {len(failures) - limit} more"
    return lines


# ---------------------------------------------------------------------------
# Month isolation
# ---------------------------------------------------------------------------

def test_month_isolation_date(month_raw, month_date_output):
    """Each month's agg_date output must carry only its own year_month label."""
    failures = []
    for month in month_raw:
        df = month_date_output.get(month, pd.DataFrame())
        if df.empty:
            continue
        wrong = df[df["year_month"] != month]
        if not wrong.empty:
            failures.append(
                f"{month}: {len(wrong)} rows have year_month != '{month}'"
            )
    assert not failures, "Month isolation violated in agg_date:\n" + "\n".join(failures)


def test_month_isolation_entity(month_raw, month_entity_output):
    """Each month's agg_entity output must carry only its own year_month label."""
    failures = []
    for month in month_raw:
        df = month_entity_output.get(month, pd.DataFrame())
        if df.empty:
            continue
        wrong = df[df["year_month"] != month]
        if not wrong.empty:
            failures.append(
                f"{month}: {len(wrong)} rows have year_month != '{month}'"
            )
    assert not failures, "Month isolation violated in agg_entity:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# Cross-script consistency for shared named entities
# ---------------------------------------------------------------------------

def test_cross_script_post_count(month_raw, month_date_output, month_entity_output):
    """For top-100 entities, summed date post_count must equal entity post_count.

    agg_date groups rows by (sentiment_pair, entity); summing post_count over
    all sentiment groups for a given entity gives the number of unique
    (tweet_id, entity) pairs for that entity.  agg_entity stores that same
    count directly.  Both scripts use identical drop_duplicates logic, so a
    mismatch indicates a join or accumulation error in one of them.
    """
    failures = []
    for month, (_, entities_df) in month_raw.items():
        date_df   = month_date_output.get(month, pd.DataFrame())
        entity_df = month_entity_output.get(month, pd.DataFrame())
        if date_df.empty or entity_df.empty:
            continue
        for entity in _top_date_entities(entities_df):
            date_count  = int(date_df.loc[date_df["entity"] == entity, "post_count"].sum())
            entity_rows = entity_df.loc[entity_df["entity"] == entity, "post_count"]
            if entity_rows.empty:
                failures.append(
                    f"{month}/{entity!r}: in agg_date top-{agg_date.TOP_N_ENTITIES}"
                    f" but absent from agg_entity output"
                )
                continue
            entity_count = int(entity_rows.item())
            if date_count != entity_count:
                failures.append(
                    f"{month}/{entity!r}: date={date_count:,}"
                    f"  entity={entity_count:,}"
                    f"  diff={date_count - entity_count:+,}"
                )
    assert not failures, (
        f"{len(failures)} post_count mismatch(es) between agg_date and agg_entity:\n"
        + _fmt_failures(failures)
    )


def test_cross_script_total_likes(month_raw, month_date_output, month_entity_output):
    """For top-100 entities, summed date total_likes must equal entity total_likes."""
    failures = []
    for month, (_, entities_df) in month_raw.items():
        date_df   = month_date_output.get(month, pd.DataFrame())
        entity_df = month_entity_output.get(month, pd.DataFrame())
        if date_df.empty or entity_df.empty:
            continue
        for entity in _top_date_entities(entities_df):
            date_val   = int(date_df.loc[date_df["entity"] == entity, "total_likes"].sum())
            entity_row = entity_df.loc[entity_df["entity"] == entity, "total_likes"]
            if entity_row.empty:
                continue
            entity_val = int(entity_row.item())
            if date_val != entity_val:
                failures.append(
                    f"{month}/{entity!r}: date={date_val:,}"
                    f"  entity={entity_val:,}"
                    f"  diff={date_val - entity_val:+,}"
                )
    assert not failures, (
        f"{len(failures)} total_likes mismatch(es):\n" + _fmt_failures(failures)
    )


def test_cross_script_total_shares(month_raw, month_date_output, month_entity_output):
    """For top-100 entities, summed date total_shares must equal entity total_shares."""
    failures = []
    for month, (_, entities_df) in month_raw.items():
        date_df   = month_date_output.get(month, pd.DataFrame())
        entity_df = month_entity_output.get(month, pd.DataFrame())
        if date_df.empty or entity_df.empty:
            continue
        for entity in _top_date_entities(entities_df):
            date_val   = int(date_df.loc[date_df["entity"] == entity, "total_shares"].sum())
            entity_row = entity_df.loc[entity_df["entity"] == entity, "total_shares"]
            if entity_row.empty:
                continue
            entity_val = int(entity_row.item())
            if date_val != entity_val:
                failures.append(
                    f"{month}/{entity!r}: date={date_val:,}"
                    f"  entity={entity_val:,}"
                    f"  diff={date_val - entity_val:+,}"
                )
    assert not failures, (
        f"{len(failures)} total_shares mismatch(es):\n" + _fmt_failures(failures)
    )


# ---------------------------------------------------------------------------
# "Other" double-count detection
# ---------------------------------------------------------------------------

def test_other_bucket_no_mixed_tweets(month_raw, month_date_output):
    """Tweets that mention a top-100 entity must NOT appear under 'Other'.

    agg_date maps every non-top entity mention to 'Other' before deduplication.
    A tweet mentioning [top_entity_A, non_top_entity_B] therefore generates
    rows for both 'top_entity_A' and 'Other', so its likes and shares are
    counted twice in the output.

    The agg_date docstring states: "'Other' groups tweets that mention *only*
    non-top entities."  This test verifies that invariant.  A failure means
    the 'Other' bucket is inflated by mixed-topic tweets and engagement totals
    are being double-counted.

    Note: the existing test_other_group_post_count in agg_date_test.py tests
    the current implementation behaviour (any tweet with a non-top entity
    counts under 'Other'); this test checks the docstring's stricter intent.
    """
    failures = []
    for month, (_, entities_df) in month_raw.items():
        date_df = month_date_output.get(month, pd.DataFrame())
        if date_df.empty or "entity" not in date_df.columns:
            continue

        top_entities = _top_date_entities(entities_df)
        top_tweet_ids = set(
            entities_df.loc[entities_df["detected_as"].isin(top_entities), "tweet_id"]
            .unique()
        )
        non_top_tweet_ids = set(
            entities_df.loc[~entities_df["detected_as"].isin(top_entities), "tweet_id"]
            .unique()
        )

        # Tweets mentioning BOTH a top-100 entity and at least one non-top entity
        mixed = top_tweet_ids & non_top_tweet_ids

        # What 'Other' post_count should be per the docstring (only-non-top tweets)
        pure_other_count = len(non_top_tweet_ids - top_tweet_ids)
        actual_other_count = int(
            date_df.loc[date_df["entity"] == "Other", "post_count"].sum()
        )

        if mixed and actual_other_count != pure_other_count:
            failures.append(
                f"{month}: 'Other' post_count={actual_other_count:,}"
                f"  docstring-expected={pure_other_count:,}"
                f"  mixed top+non-top tweets={len(mixed):,}"
                f"  over-count={actual_other_count - pure_other_count:+,}"
            )

    assert not failures, (
        "'Other' bucket contains tweets that also mention top-100 entities "
        "(double-counting — docstring says 'only non-top' but implementation "
        "counts 'any non-top'):\n" + "\n".join(failures)
    )


# ---------------------------------------------------------------------------
# Per-entity raw verification across months
# ---------------------------------------------------------------------------

def test_top5_entities_per_month_against_raw(month_raw, month_entity_output):
    """Verify post_count, total_likes, total_shares for the top-5 entities per month.

    Expected values are derived independently from the raw Parquet files —
    not from the script under test.  Running across multiple months means an
    error in one month cannot be masked by a passing month.  A failure here
    points to a join, dedup, or accumulation error in agg_entity.process_month.
    """
    failures = []
    for month, (tweets_df, entities_df) in month_raw.items():
        entity_df = month_entity_output.get(month, pd.DataFrame())
        if entity_df.empty:
            continue

        top5 = (
            entities_df.groupby("detected_as")["tweet_id"]
            .nunique()
            .nlargest(5)
            .index
            .tolist()
        )

        for entity in top5:
            expected_ids = set(
                entities_df.loc[entities_df["detected_as"] == entity, "tweet_id"]
                .unique()
            )
            expected_count  = len(expected_ids)
            expected_likes  = int(
                tweets_df.loc[tweets_df["tweet_id"].isin(expected_ids), "likes"].sum()
            )
            expected_shares = int(
                tweets_df.loc[tweets_df["tweet_id"].isin(expected_ids), "shares"].sum()
            )

            row = entity_df.loc[entity_df["entity"] == entity]
            if row.empty:
                failures.append(f"{month}/{entity!r}: missing from output")
                continue

            actual_count  = int(row["post_count"].item())
            actual_likes  = int(row["total_likes"].item())
            actual_shares = int(row["total_shares"].item())

            if actual_count != expected_count:
                failures.append(
                    f"{month}/{entity!r}: post_count={actual_count:,}"
                    f"  expected={expected_count:,}"
                    f"  diff={actual_count - expected_count:+,}"
                )
            if actual_likes != expected_likes:
                failures.append(
                    f"{month}/{entity!r}: total_likes={actual_likes:,}"
                    f"  expected={expected_likes:,}"
                    f"  diff={actual_likes - expected_likes:+,}"
                )
            if actual_shares != expected_shares:
                failures.append(
                    f"{month}/{entity!r}: total_shares={actual_shares:,}"
                    f"  expected={expected_shares:,}"
                    f"  diff={actual_shares - expected_shares:+,}"
                )

    assert not failures, (
        f"{len(failures)} per-entity raw mismatch(es) in agg_entity:\n"
        + _fmt_failures(failures)
    )
