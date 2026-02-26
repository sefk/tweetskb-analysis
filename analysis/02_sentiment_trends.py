"""
Analysis 2: Sentiment Trends Over Time

For each month, computes the weighted-average positive and negative
sentiment across classified, non-redacted rows in date.parquet
(weighted by post_count).  Prints the 10 most positive and 10 most
negative months.

Note: the Dec 2017 – Mar 2018 gap months have near-zero post counts
and will appear at the top of the negative list as an artefact of the
data anomaly — treat those results with scepticism.
"""

import pandas as pd

DATA_DIR = "/Users/sefk/src/stanford-dataviz/tweetskb-analysis/tweetskb_tables"


def main():
    df = pd.read_parquet(f"{DATA_DIR}/date.parquet")
    df["year_month"] = pd.to_datetime(df["year_month"], format="%Y-%m")

    # Standard clean filter
    clean = df[df["classified"] & ~df["redacted"]].copy()
    clean["pos_weighted"] = clean["positive_sentiment"] * clean["post_count"]
    clean["neg_weighted"] = clean["negative_sentiment"] * clean["post_count"]

    monthly = clean.groupby("year_month").agg(
        total_posts=("post_count", "sum"),
        pos_weighted_sum=("pos_weighted", "sum"),
        neg_weighted_sum=("neg_weighted", "sum"),
    ).reset_index()
    monthly["avg_positive"] = monthly["pos_weighted_sum"] / monthly["total_posts"]
    monthly["avg_negative"] = monthly["neg_weighted_sum"] / monthly["total_posts"]
    monthly["sentiment_net"] = monthly["avg_positive"] - monthly["avg_negative"]

    hdr = (
        f"{'Year-Month':<14} {'Avg Positive':>14} {'Avg Negative':>14}"
        f" {'Net Sentiment':>14} {'Posts':>14}"
    )
    sep = "-" * 74

    print("=" * 70)
    print("ANALYSIS 2: Sentiment Trends Over Time (classified, non-redacted)")
    print("=" * 70)

    print("\nTop 10 Most POSITIVE Months (weighted avg positive sentiment):")
    print(hdr)
    print(sep)
    for _, r in monthly.nlargest(10, "avg_positive").iterrows():
        print(
            f"{r['year_month'].strftime('%Y-%m'):<14}"
            f" {r['avg_positive']:>14.4f}"
            f" {r['avg_negative']:>14.4f}"
            f" {r['sentiment_net']:>14.4f}"
            f" {r['total_posts']:>14,.0f}"
        )

    print("\nTop 10 Most NEGATIVE Months (weighted avg negative sentiment):")
    print(hdr)
    print(sep)
    for _, r in monthly.nlargest(10, "avg_negative").iterrows():
        print(
            f"{r['year_month'].strftime('%Y-%m'):<14}"
            f" {r['avg_positive']:>14.4f}"
            f" {r['avg_negative']:>14.4f}"
            f" {r['sentiment_net']:>14.4f}"
            f" {r['total_posts']:>14,.0f}"
        )


if __name__ == "__main__":
    main()
