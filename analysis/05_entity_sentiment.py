"""
Analysis 5: Sentiment Outliers Among Top Entities

For the top 100 entities by total post count (classified, non-redacted),
computes the post-count-weighted average positive and negative sentiment
over all months.  Prints the 10 most positive and 10 most negative entities.
"""

import pandas as pd

DATA_DIR = "/Users/sefk/src/stanford-dataviz/tweetskb-analysis/tweetskb_tables"


def main():
    df = pd.read_parquet(f"{DATA_DIR}/entity.parquet")
    df["year_month"] = pd.to_datetime(df["year_month"], format="%Y-%m")

    clean = df[df["classified"] & ~df["redacted"]].copy()

    top100 = (
        clean.groupby("entity")["post_count"].sum().nlargest(100).index.tolist()
    )
    subset = clean[clean["entity"].isin(top100)].copy()

    subset["pos_weighted"] = subset["positive_sentiment"] * subset["post_count"]
    subset["neg_weighted"] = subset["negative_sentiment"] * subset["post_count"]

    ent_sent = subset.groupby("entity").agg(
        total_posts=("post_count", "sum"),
        pos_weighted_sum=("pos_weighted", "sum"),
        neg_weighted_sum=("neg_weighted", "sum"),
    ).reset_index()
    ent_sent["avg_positive"] = ent_sent["pos_weighted_sum"] / ent_sent["total_posts"]
    ent_sent["avg_negative"] = ent_sent["neg_weighted_sum"] / ent_sent["total_posts"]
    ent_sent["sentiment_net"] = ent_sent["avg_positive"] - ent_sent["avg_negative"]

    hdr = (
        f"{'Entity':<35} {'Total Posts':>12} {'Avg Positive':>14}"
        f" {'Avg Negative':>14} {'Net':>10}"
    )
    sep = "-" * 88

    print("=" * 70)
    print("ANALYSIS 5: Sentiment Outliers — Top 100 Entities by Total Posts")
    print("=" * 70)

    print("\nTop 10 Most POSITIVE entities (weighted avg positive sentiment):")
    print(hdr)
    print(sep)
    for _, r in ent_sent.nlargest(10, "avg_positive").iterrows():
        print(
            f"{r['entity']:<35} {r['total_posts']:>12,.0f}"
            f" {r['avg_positive']:>14.4f}"
            f" {r['avg_negative']:>14.4f}"
            f" {r['sentiment_net']:>10.4f}"
        )

    print("\nTop 10 Most NEGATIVE entities (weighted avg negative sentiment):")
    print(hdr)
    print(sep)
    for _, r in ent_sent.nlargest(10, "avg_negative").iterrows():
        print(
            f"{r['entity']:<35} {r['total_posts']:>12,.0f}"
            f" {r['avg_positive']:>14.4f}"
            f" {r['avg_negative']:>14.4f}"
            f" {r['sentiment_net']:>10.4f}"
        )


if __name__ == "__main__":
    main()
