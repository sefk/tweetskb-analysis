#!/usr/bin/env python3
"""
agg_entity_test.py

Data quality tests for agg_entity.py.  Runs process_month against one month of
raw data in tweetskb_ready/ and verifies invariants on the aggregated output.

Usage:
    pytest agg_entity_test.py                    # default: 2013-01
    pytest agg_entity_test.py --month 2014-06    # test a specific month
    pytest agg_entity_test.py -v                 # verbose output

Note: --month is registered in conftest.py (shared with agg_date_test.py).
"""

import hashlib
import multiprocessing as mp
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest
from better_profanity import profanity

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agg_entity import TOP_N_ENTITIES, process_month

READY_DIR = Path(__file__).resolve().parent / "tweetskb_ready"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def month(pytestconfig):
    return pytestconfig.getoption("month")


@pytest.fixture(scope="session")
def raw_data(month):
    """Load raw tweets and entities for the test month."""
    tweets_path = READY_DIR / f"month_{month}_tweets.parquet"
    entities_path = READY_DIR / f"month_{month}_entities.parquet"

    if not tweets_path.exists():
        pytest.skip(f"Missing tweets file: {tweets_path}")
    if not entities_path.exists():
        pytest.skip(f"Missing entities file: {entities_path}")

    tweets_df = pq.read_table(
        str(tweets_path),
        columns=["tweet_id", "likes", "shares", "positive_emotion", "negative_emotion"],
    ).to_pandas()
    tweets_df["likes"]  = tweets_df["likes"].fillna(0).astype("int64")
    tweets_df["shares"] = tweets_df["shares"].fillna(0).astype("int64")

    entities_df = pq.read_table(
        str(entities_path), columns=["tweet_id", "detected_as"]
    ).to_pandas()

    return tweets_df, entities_df


@pytest.fixture(scope="session")
def top_entities(raw_data):
    """Set of top-N entity names for the test month (matches pipeline logic)."""
    _, entities_df = raw_data
    return set(
        entities_df.groupby("detected_as")["tweet_id"]
        .nunique()
        .nlargest(TOP_N_ENTITIES)
        .index
    )


@pytest.fixture(scope="session")
def ent_deduped(raw_data, top_entities):
    """Deduped (tweet_id, entity) table for top-N entities, mirroring pipeline logic."""
    _, entities_df = raw_data
    return (
        entities_df[entities_df["detected_as"].isin(top_entities)]
        [["tweet_id", "detected_as"]]
        .drop_duplicates()
        .rename(columns={"detected_as": "entity"})
    )


@pytest.fixture(scope="session")
def output_df(month, raw_data):
    """Run process_month and return the aggregated DataFrame."""
    tweets_path = READY_DIR / f"month_{month}_tweets.parquet"
    entities_path = READY_DIR / f"month_{month}_entities.parquet"

    manager = mp.Manager()
    slot_queue = manager.Queue()
    slot_queue.put(0)
    stop_event = manager.Event()   # not set → run to completion

    rows = process_month((month, tweets_path, entities_path, slot_queue, stop_event))
    manager.shutdown()

    df = pd.DataFrame(rows)

    # Mirror main()'s redaction step so the fixture matches the real output schema.
    dirty = {e for e in df["entity"].unique() if profanity.contains_profanity(e)}
    redaction_map = {
        e: f"[REDACTED_{hashlib.md5(e.encode()).hexdigest()[:6]}]" for e in dirty
    }
    if redaction_map:
        df["entity"] = df["entity"].replace(redaction_map)
    df["redacted"]   = df["entity"].isin(set(redaction_map.values()))
    df["classified"] = ~df["entity"].isin({"Other", "None"})

    return df


# ---------------------------------------------------------------------------
# Schema / structural tests
# ---------------------------------------------------------------------------

def test_output_not_empty(output_df):
    """Output must contain at least one row."""
    assert len(output_df) > 0


def test_no_duplicate_entities(output_df):
    """Each entity must appear at most once (one row per entity per month)."""
    dupes = output_df.duplicated(subset=["entity"])
    assert not dupes.any(), (
        f"Duplicate entities:\n{output_df[dupes]['entity'].tolist()}"
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


def test_redacted_column_is_bool(output_df):
    """The redacted column must exist and contain only boolean values."""
    assert "redacted" in output_df.columns
    assert output_df["redacted"].dtype == bool


def test_redacted_false_for_clean_entities(output_df):
    """Entities that are not redaction tokens must have redacted=False."""
    clean_mask = ~output_df["entity"].str.startswith("[REDACTED_")
    assert not output_df.loc[clean_mask, "redacted"].any(), (
        "redacted=True found for entities that are not redaction tokens"
    )


def test_redacted_true_for_redacted_entities(output_df):
    """Entities that are redaction tokens must have redacted=True."""
    redacted_mask = output_df["entity"].str.startswith("[REDACTED_")
    assert output_df.loc[redacted_mask, "redacted"].all(), (
        "redacted=False found for entities that are redaction tokens"
    )


def test_classified_column_is_bool(output_df):
    """The classified column must exist and contain only boolean values."""
    assert "classified" in output_df.columns
    assert output_df["classified"].dtype == bool


def test_classified_true_for_all_entities(output_df):
    """agg_entity only contains named entities, so classified must be True for every row."""
    assert output_df["classified"].all(), (
        "classified=False found in agg_entity output (no 'Other'/'None' rows expected)"
    )


# ---------------------------------------------------------------------------
# Sentiment range tests
# ---------------------------------------------------------------------------

def test_positive_sentiment_in_range(output_df):
    """positive_sentiment (a mean) must be in [0.0, 1.0]."""
    assert output_df["positive_sentiment"].between(0.0, 1.0).all(), (
        f"Out-of-range values: {output_df.loc[~output_df['positive_sentiment'].between(0.0, 1.0), 'positive_sentiment'].unique()}"
    )


def test_negative_sentiment_in_range(output_df):
    """negative_sentiment (a mean) must be in [0.0, 1.0]."""
    assert output_df["negative_sentiment"].between(0.0, 1.0).all(), (
        f"Out-of-range values: {output_df.loc[~output_df['negative_sentiment'].between(0.0, 1.0), 'negative_sentiment'].unique()}"
    )


# ---------------------------------------------------------------------------
# Entity membership tests
# ---------------------------------------------------------------------------

def test_entity_count(output_df):
    """Output must have at most TOP_N_ENTITIES distinct entities."""
    n = output_df["entity"].nunique()
    assert n <= TOP_N_ENTITIES, (
        f"Too many distinct entities: {n} (limit is {TOP_N_ENTITIES})"
    )


def test_entities_are_top_n(output_df, top_entities):
    """Every non-redacted entity in the output must be among the top-N for the month."""
    not_top = set(output_df.loc[~output_df["redacted"], "entity"].unique()) - top_entities
    assert not not_top, (
        f"Entities in output not in top-{TOP_N_ENTITIES}: {not_top}"
    )


# ---------------------------------------------------------------------------
# Total post_count invariant
# ---------------------------------------------------------------------------

def test_total_post_count(output_df, ent_deduped):
    """Total post_count must equal the number of unique (tweet_id, top-entity) pairs."""
    expected = len(ent_deduped)
    actual   = int(output_df["post_count"].sum())
    assert actual == expected, (
        f"Total post_count: expected {expected:,}, got {actual:,}"
    )


# ---------------------------------------------------------------------------
# Per-entity correctness (verified against the most-mentioned entity)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def top_entity_name(output_df):
    """Entity with the highest post_count in the output."""
    return output_df.loc[output_df["post_count"].idxmax(), "entity"]


@pytest.fixture(scope="session")
def top_entity_tweet_ids(top_entity_name, ent_deduped):
    """Set of tweet_ids that mention the top entity (after dedup, matching pipeline)."""
    return set(ent_deduped.loc[ent_deduped["entity"] == top_entity_name, "tweet_id"])


def test_top_entity_post_count(output_df, top_entity_name, top_entity_tweet_ids):
    """The most-mentioned entity's post_count must equal its unique tweet count."""
    expected = len(top_entity_tweet_ids)
    actual   = int(output_df.loc[output_df["entity"] == top_entity_name, "post_count"].item())
    assert actual == expected, (
        f"post_count for '{top_entity_name}': expected {expected:,}, got {actual:,}"
    )


def test_top_entity_likes_sum(output_df, raw_data, top_entity_name, top_entity_tweet_ids):
    """The most-mentioned entity's total_likes must equal the sum of likes for its tweets."""
    tweets_df, _ = raw_data
    expected = int(tweets_df.loc[tweets_df["tweet_id"].isin(top_entity_tweet_ids), "likes"].sum())
    actual   = int(output_df.loc[output_df["entity"] == top_entity_name, "total_likes"].item())
    assert actual == expected, (
        f"total_likes for '{top_entity_name}': expected {expected:,}, got {actual:,}"
    )


def test_top_entity_shares_sum(output_df, raw_data, top_entity_name, top_entity_tweet_ids):
    """The most-mentioned entity's total_shares must equal the sum of shares for its tweets."""
    tweets_df, _ = raw_data
    expected = int(tweets_df.loc[tweets_df["tweet_id"].isin(top_entity_tweet_ids), "shares"].sum())
    actual   = int(output_df.loc[output_df["entity"] == top_entity_name, "total_shares"].item())
    assert actual == expected, (
        f"total_shares for '{top_entity_name}': expected {expected:,}, got {actual:,}"
    )


def test_top_entity_positive_sentiment(output_df, raw_data, top_entity_name, top_entity_tweet_ids):
    """The most-mentioned entity's positive_sentiment must equal the mean of non-zero quantized scores."""
    tweets_df, _ = raw_data
    relevant  = tweets_df.loc[tweets_df["tweet_id"].isin(top_entity_tweet_ids), "positive_emotion"]
    quantized = relevant.fillna(0.0).mul(4).round().div(4)
    nonzero   = quantized[quantized > 0]
    expected  = float(nonzero.sum() / len(nonzero)) if len(nonzero) > 0 else 0.0
    actual    = float(output_df.loc[output_df["entity"] == top_entity_name, "positive_sentiment"].item())
    assert abs(actual - expected) < 1e-4, (
        f"positive_sentiment for '{top_entity_name}': expected {expected:.6f}, got {actual:.6f}"
    )


def test_top_entity_negative_sentiment(output_df, raw_data, top_entity_name, top_entity_tweet_ids):
    """The most-mentioned entity's negative_sentiment must equal the mean of non-zero quantized scores."""
    tweets_df, _ = raw_data
    relevant  = tweets_df.loc[tweets_df["tweet_id"].isin(top_entity_tweet_ids), "negative_emotion"]
    quantized = relevant.fillna(0.0).mul(4).round().div(4)
    nonzero   = quantized[quantized > 0]
    expected  = float(nonzero.sum() / len(nonzero)) if len(nonzero) > 0 else 0.0
    actual    = float(output_df.loc[output_df["entity"] == top_entity_name, "negative_sentiment"].item())
    assert abs(actual - expected) < 1e-4, (
        f"negative_sentiment for '{top_entity_name}': expected {expected:.6f}, got {actual:.6f}"
    )


# ---------------------------------------------------------------------------
# Global likes / shares lower-bound
# ---------------------------------------------------------------------------

def test_total_likes_ge_entity_tweets(output_df, raw_data, top_entities):
    """Output total_likes must be >= sum of likes for tweets mentioning any top-N entity.

    Tweets mentioning multiple top-N entities are counted once per entity, so
    the output sum can exceed the single-count input.  If it falls below, data
    was lost.
    """
    tweets_df, entities_df = raw_data
    entity_tweet_ids = set(
        entities_df[entities_df["detected_as"].isin(top_entities)]["tweet_id"].unique()
    )
    input_total  = int(tweets_df.loc[tweets_df["tweet_id"].isin(entity_tweet_ids), "likes"].sum())
    output_total = int(output_df["total_likes"].sum())
    assert output_total >= input_total, (
        f"Output likes ({output_total:,}) < likes for entity-tweets ({input_total:,}): data was lost"
    )


def test_total_shares_ge_entity_tweets(output_df, raw_data, top_entities):
    """Output total_shares must be >= sum of shares for tweets mentioning any top-N entity."""
    tweets_df, entities_df = raw_data
    entity_tweet_ids = set(
        entities_df[entities_df["detected_as"].isin(top_entities)]["tweet_id"].unique()
    )
    input_total  = int(tweets_df.loc[tweets_df["tweet_id"].isin(entity_tweet_ids), "shares"].sum())
    output_total = int(output_df["total_shares"].sum())
    assert output_total >= input_total, (
        f"Output shares ({output_total:,}) < shares for entity-tweets ({input_total:,}): data was lost"
    )
