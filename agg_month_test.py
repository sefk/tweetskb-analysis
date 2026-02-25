#!/usr/bin/env python3
"""
agg_month_test.py

Data quality tests for agg_month.py.  Runs process_month against one month of
raw data in tweetskb_ready/ and verifies invariants on the aggregated output.

Usage:
    pytest agg_month_test.py                    # default: 2013-01
    pytest agg_month_test.py --month 2014-06    # test a specific month
    pytest agg_month_test.py -v                 # verbose output
"""

import multiprocessing as mp
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agg_month import process_month

READY_DIR = Path(__file__).resolve().parent / "tweetskb_ready"
VALID_SENTIMENT = frozenset({0.0, 0.25, 0.5, 0.75, 1.0})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def month(pytestconfig):
    return pytestconfig.getoption("month")


@pytest.fixture(scope="session")
def raw_tweets(month):
    """Load the raw tweets for the test month."""
    tweets_path = READY_DIR / f"month_{month}_tweets.parquet"
    if not tweets_path.exists():
        pytest.skip(f"Missing tweets file: {tweets_path}")

    df = pq.read_table(
        str(tweets_path),
        columns=["tweet_id", "likes", "shares", "positive_emotion", "negative_emotion"],
    ).to_pandas()
    df["likes"]  = df["likes"].fillna(0).astype("int64")
    df["shares"] = df["shares"].fillna(0).astype("int64")
    return df


@pytest.fixture(scope="session")
def output_df(month):
    """Run process_month and return the aggregated DataFrame."""
    tweets_path = READY_DIR / f"month_{month}_tweets.parquet"
    if not tweets_path.exists():
        pytest.skip(f"Missing tweets file: {tweets_path}")

    manager = mp.Manager()
    slot_queue = manager.Queue()
    slot_queue.put(0)   # one slot is enough for a single worker
    stop_event = manager.Event()

    rows = process_month((month, tweets_path, slot_queue, stop_event))
    manager.shutdown()

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Schema / structural tests
# ---------------------------------------------------------------------------

def test_output_not_empty(output_df):
    """Output must contain at least one row."""
    assert len(output_df) > 0


def test_no_duplicate_keys(output_df):
    """Each (positive_sentiment, negative_sentiment) combination must be unique."""
    key_cols = ["positive_sentiment", "negative_sentiment"]
    dupes = output_df.duplicated(subset=key_cols)
    assert not dupes.any(), (
        f"Duplicate keys found:\n{output_df[dupes][key_cols]}"
    )


def test_sentiment_values_valid(output_df):
    """All sentiment values must be in the canonical set {0.0, 0.25, 0.5, 0.75, 1.0}."""
    bad_pos = ~output_df["positive_sentiment"].isin(VALID_SENTIMENT)
    bad_neg = ~output_df["negative_sentiment"].isin(VALID_SENTIMENT)
    assert not bad_pos.any(), (
        f"Invalid positive_sentiment values: "
        f"{sorted(output_df.loc[bad_pos, 'positive_sentiment'].unique())}"
    )
    assert not bad_neg.any(), (
        f"Invalid negative_sentiment values: "
        f"{sorted(output_df.loc[bad_neg, 'negative_sentiment'].unique())}"
    )


def test_row_count_at_most_25(output_df):
    """Output must have at most 25 rows (5 × 5 sentiment combinations)."""
    assert len(output_df) <= 25, (
        f"Too many rows: {len(output_df)} (max is 25)"
    )


def test_post_count_positive(output_df):
    """Every output row must have a positive post_count."""
    assert (output_df["post_count"] > 0).all()


def test_likes_nonnegative(output_df):
    """total_likes must be non-negative in every row."""
    assert (output_df["total_likes"] >= 0).all()


def test_shares_nonnegative(output_df):
    """total_shares must be non-negative in every row."""
    assert (output_df["total_shares"] >= 0).all()


def test_year_month_field(output_df, month):
    """All rows must carry the correct year_month label."""
    assert (output_df["year_month"] == month).all()


def test_no_entity_columns(output_df):
    """Output must not contain entity, redacted, or classified columns."""
    for col in ("entity", "redacted", "classified"):
        assert col not in output_df.columns, (
            f"Unexpected column '{col}' found in output"
        )


# ---------------------------------------------------------------------------
# Count / sum invariants
# ---------------------------------------------------------------------------

def test_total_post_count_equals_tweet_count(output_df, raw_tweets):
    """Total post_count must equal the number of tweets in the input file.

    Unlike agg_date.py, there is no entity join — every tweet contributes
    exactly once, so the sum must be exact.
    """
    expected = len(raw_tweets)
    actual   = int(output_df["post_count"].sum())
    assert actual == expected, (
        f"Total post_count: expected {expected:,}, got {actual:,}"
    )


def test_total_likes_equals_input(output_df, raw_tweets):
    """Output total_likes must equal the sum of raw likes exactly.

    There is no row expansion (unlike agg_date.py), so sums must match exactly.
    """
    expected = int(raw_tweets["likes"].sum())
    actual   = int(output_df["total_likes"].sum())
    assert actual == expected, (
        f"Total likes: expected {expected:,}, got {actual:,}"
    )


def test_total_shares_equals_input(output_df, raw_tweets):
    """Output total_shares must equal the sum of raw shares exactly."""
    expected = int(raw_tweets["shares"].sum())
    actual   = int(output_df["total_shares"].sum())
    assert actual == expected, (
        f"Total shares: expected {expected:,}, got {actual:,}"
    )
