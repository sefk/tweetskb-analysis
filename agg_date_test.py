#!/usr/bin/env python3
"""
agg_date_test.py

Data quality tests for agg_date.py.  Runs process_month against one month of
raw data in tweetskb_ready/ and verifies invariants on the aggregated output.

Usage:
    pytest agg_date_test.py                    # default: 2013-01
    pytest agg_date_test.py --month 2014-06    # test a specific month
    pytest agg_date_test.py -v                 # verbose output
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

from agg_date import TOP_N_ENTITIES, process_month

READY_DIR = Path(__file__).resolve().parent / "tweetskb_ready"
VALID_SENTIMENT = frozenset({0.0, 0.25, 0.5, 0.75, 1.0})


# ---------------------------------------------------------------------------
# CLI option
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def month(pytestconfig):
    return pytestconfig.getoption("month")


@pytest.fixture(scope="session")
def raw_data(month):
    """Load the raw tweets and entities for the test month."""
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
    """Set of top-N entity names for the test month."""
    _, entities_df = raw_data
    return set(
        entities_df.groupby("detected_as")["tweet_id"]
        .nunique()
        .nlargest(TOP_N_ENTITIES)
        .index
    )


@pytest.fixture(scope="session")
def output_df(month, raw_data):
    """Run process_month and return the aggregated DataFrame."""
    tweets_path = READY_DIR / f"month_{month}_tweets.parquet"
    entities_path = READY_DIR / f"month_{month}_entities.parquet"

    manager = mp.Manager()
    slot_queue = manager.Queue()
    slot_queue.put(0)   # one slot is enough for a single worker
    stop_event = manager.Event()

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


def test_no_duplicate_keys(output_df):
    """Each (positive_sentiment, negative_sentiment, entity) combination must be unique."""
    key_cols = ["positive_sentiment", "negative_sentiment", "entity"]
    dupes = output_df.duplicated(subset=key_cols)
    assert not dupes.any(), (
        f"Duplicate keys found:\n{output_df[dupes][key_cols]}"
    )


def test_sentiment_values_valid(output_df):
    """All sentiment values must be in the canonical set {0.0, 0.25, 0.5, 0.75, 1.0}."""
    bad_pos = ~output_df["positive_sentiment"].isin(VALID_SENTIMENT)
    bad_neg = ~output_df["negative_sentiment"].isin(VALID_SENTIMENT)
    assert not bad_pos.any(), (
        f"Invalid positive_sentiment values: {sorted(output_df.loc[bad_pos, 'positive_sentiment'].unique())}"
    )
    assert not bad_neg.any(), (
        f"Invalid negative_sentiment values: {sorted(output_df.loc[bad_neg, 'negative_sentiment'].unique())}"
    )


def test_entity_count(output_df):
    """Output must have at most TOP_N_ENTITIES + 2 distinct entities ('Other' and 'None')."""
    n = output_df["entity"].nunique()
    assert n <= TOP_N_ENTITIES + 2, (
        f"Too many distinct entities: {n} (limit is {TOP_N_ENTITIES + 2})"
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


def test_classified_false_for_other_and_none(output_df):
    """'Other' and 'None' entities must have classified=False."""
    sentinel_mask = output_df["entity"].isin({"Other", "None"})
    assert not output_df.loc[sentinel_mask, "classified"].any(), (
        "classified=True found for 'Other' or 'None' entity"
    )


def test_classified_true_for_named_entities(output_df):
    """All entities that are not 'Other' or 'None' must have classified=True."""
    named_mask = ~output_df["entity"].isin({"Other", "None"})
    assert output_df.loc[named_mask, "classified"].all(), (
        "classified=False found for a named entity"
    )


# ---------------------------------------------------------------------------
# Entity membership tests
# ---------------------------------------------------------------------------

def test_named_entities_are_top(output_df, top_entities):
    """Every non-redacted entity other than 'Other' and 'None' must be a top-N entity."""
    named = set(output_df.loc[~output_df["redacted"], "entity"].unique()) - {"Other", "None"}
    not_top = named - top_entities
    assert not not_top, (
        f"Entities in output not in top-{TOP_N_ENTITIES}: {not_top}"
    )


def test_other_present_when_non_top_entities_exist(output_df, raw_data, top_entities):
    """'Other' entity must appear when some tweets mention only non-top entities."""
    _, entities_df = raw_data
    non_top_ids = set(
        entities_df.loc[~entities_df["detected_as"].isin(top_entities), "tweet_id"].unique()
    )
    top_ids = set(
        entities_df.loc[entities_df["detected_as"].isin(top_entities), "tweet_id"].unique()
    )
    has_pure_non_top = bool(non_top_ids - top_ids)
    if has_pure_non_top:
        assert "Other" in set(output_df["entity"].unique()), (
            "'Other' entity missing despite pure non-top-entity tweets existing"
        )


def test_none_present_when_entityless_tweets_exist(output_df, raw_data):
    """'None' entity must appear when some tweets have no detected entity."""
    tweets_df, entities_df = raw_data
    has_no_entity = (~tweets_df["tweet_id"].isin(set(entities_df["tweet_id"]))).any()
    if has_no_entity:
        assert "None" in set(output_df["entity"].unique()), (
            "'None' entity missing despite tweets with no entity existing"
        )


# ---------------------------------------------------------------------------
# 'None' group invariants (tweets with no detected entity)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def no_entity_tweets(raw_data):
    """Subset of tweets_df whose tweet_id does not appear in the entities file."""
    tweets_df, entities_df = raw_data
    return tweets_df[~tweets_df["tweet_id"].isin(set(entities_df["tweet_id"]))]


def test_none_group_post_count(output_df, no_entity_tweets):
    """post_count for 'None' rows must equal the number of tweets with no entity."""
    expected = len(no_entity_tweets)
    actual   = int(output_df.loc[output_df["entity"] == "None", "post_count"].sum())
    assert actual == expected, (
        f"'None' post_count: expected {expected}, got {actual}"
    )


def test_none_group_likes_sum(output_df, no_entity_tweets):
    """total_likes for 'None' rows must equal the sum of likes for no-entity tweets."""
    expected = int(no_entity_tweets["likes"].sum())
    actual   = int(output_df.loc[output_df["entity"] == "None", "total_likes"].sum())
    assert actual == expected, (
        f"'None' total_likes: expected {expected:,}, got {actual:,}"
    )


def test_none_group_shares_sum(output_df, no_entity_tweets):
    """total_shares for 'None' rows must equal the sum of shares for no-entity tweets."""
    expected = int(no_entity_tweets["shares"].sum())
    actual   = int(output_df.loc[output_df["entity"] == "None", "total_shares"].sum())
    assert actual == expected, (
        f"'None' total_shares: expected {expected:,}, got {actual:,}"
    )


# ---------------------------------------------------------------------------
# 'Other' group invariants (tweets with at least one non-top entity)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def other_tweet_ids(raw_data, top_entities):
    """Set of tweet_ids that mention only non-top entities (no top-100 entity at all).

    These are the tweets that land in the 'Other' bucket after the fix that
    excludes mixed-topic tweets (which already appear under their named entity).
    """
    _, entities_df = raw_data
    non_top = set(
        entities_df.loc[~entities_df["detected_as"].isin(top_entities), "tweet_id"].unique()
    )
    top = set(
        entities_df.loc[entities_df["detected_as"].isin(top_entities), "tweet_id"].unique()
    )
    return non_top - top


def test_other_group_post_count(output_df, other_tweet_ids):
    """post_count for 'Other' rows must equal the number of tweets with any non-top entity."""
    expected = len(other_tweet_ids)
    actual   = int(output_df.loc[output_df["entity"] == "Other", "post_count"].sum())
    assert actual == expected, (
        f"'Other' post_count: expected {expected}, got {actual}"
    )


def test_other_group_likes_sum(output_df, raw_data, other_tweet_ids):
    """total_likes for 'Other' rows must equal likes summed over tweets with any non-top entity."""
    tweets_df, _ = raw_data
    expected = int(tweets_df.loc[tweets_df["tweet_id"].isin(other_tweet_ids), "likes"].sum())
    actual   = int(output_df.loc[output_df["entity"] == "Other", "total_likes"].sum())
    assert actual == expected, (
        f"'Other' total_likes: expected {expected:,}, got {actual:,}"
    )


def test_other_group_shares_sum(output_df, raw_data, other_tweet_ids):
    """total_shares for 'Other' rows must equal shares summed over tweets with any non-top entity."""
    tweets_df, _ = raw_data
    expected = int(tweets_df.loc[tweets_df["tweet_id"].isin(other_tweet_ids), "shares"].sum())
    actual   = int(output_df.loc[output_df["entity"] == "Other", "total_shares"].sum())
    assert actual == expected, (
        f"'Other' total_shares: expected {expected:,}, got {actual:,}"
    )


# ---------------------------------------------------------------------------
# Total post_count invariant
# ---------------------------------------------------------------------------

def test_total_post_count(output_df, raw_data, top_entities):
    """Total post_count must equal the number of unique (tweet_id, entity_label) pairs.

    Each tweet contributes one row per top-N entity it mentions, one row under
    'Other' if it mentions only non-top entities, and one row under 'None' if it
    has no detected entity at all.  This mirrors exactly how the pipeline builds
    the 'ent' join table before merging with tweets.
    """
    tweets_df, entities_df = raw_data

    # Reproduce the pipeline's entity labelling (including the mixed-tweet fix)
    ent_full = entities_df.copy()
    ent_full["entity"] = ent_full["detected_as"].where(
        ent_full["detected_as"].isin(top_entities), other="Other"
    )
    ent = ent_full[["tweet_id", "entity"]].drop_duplicates()
    top_tweet_ids = set(ent.loc[ent["entity"] != "Other", "tweet_id"])
    ent = ent[~((ent["entity"] == "Other") & ent["tweet_id"].isin(top_tweet_ids))]
    n_entity_pairs = len(ent)

    tweet_ids_with_entity = set(entities_df["tweet_id"].unique())
    n_no_entity = int((~tweets_df["tweet_id"].isin(tweet_ids_with_entity)).sum())

    expected = n_entity_pairs + n_no_entity
    actual   = int(output_df["post_count"].sum())
    assert actual == expected, (
        f"Total post_count: expected {expected:,}, got {actual:,}"
    )


# ---------------------------------------------------------------------------
# Likes / shares lower-bound test
# ---------------------------------------------------------------------------

def test_total_likes_ge_input(output_df, raw_data):
    """Output total_likes must be >= input total_likes.

    Tweets mentioning multiple top-N entities are counted once per entity, so
    the output sum can exceed the input sum.  If it's less, data was lost.
    """
    tweets_df, _ = raw_data
    input_total  = int(tweets_df["likes"].sum())
    output_total = int(output_df["total_likes"].sum())
    assert output_total >= input_total, (
        f"Output likes ({output_total:,}) < input likes ({input_total:,}): data was lost"
    )


def test_total_shares_ge_input(output_df, raw_data):
    """Output total_shares must be >= input total_shares (same reasoning as likes)."""
    tweets_df, _ = raw_data
    input_total  = int(tweets_df["shares"].sum())
    output_total = int(output_df["total_shares"].sum())
    assert output_total >= input_total, (
        f"Output shares ({output_total:,}) < input shares ({input_total:,}): data was lost"
    )
