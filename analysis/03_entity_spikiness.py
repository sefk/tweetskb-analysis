"""
Analysis 3: Entity Rise and Fall — Spikiness

Among the top 50 entities by total post count (classified, non-redacted),
finds each entity's single peak month and computes "spikiness":

    spikiness = peak_month_posts / lifetime_total_posts

A high spikiness score means the entity was essentially a one-month
viral moment rather than a sustained topic.  Prints the 20 spikiest.
"""

import pandas as pd

DATA_DIR = "/Users/sefk/src/stanford-dataviz/tweetskb-analysis/tweetskb_tables"


def main():
    df = pd.read_parquet(f"{DATA_DIR}/entity.parquet")
    df["year_month"] = pd.to_datetime(df["year_month"], format="%Y-%m")

    clean = df[df["classified"] & ~df["redacted"]]

    top50_entities = (
        clean.groupby("entity")["post_count"].sum().nlargest(50).index.tolist()
    )
    subset = clean[clean["entity"].isin(top50_entities)]

    rows = []
    for entity, grp in subset.groupby("entity"):
        total = grp["post_count"].sum()
        peak_idx = grp["post_count"].idxmax()
        peak_month = grp.loc[peak_idx, "year_month"]
        peak_count = grp.loc[peak_idx, "post_count"]
        rows.append(
            {
                "entity": entity,
                "total_posts": total,
                "peak_month": peak_month,
                "peak_count": peak_count,
                "spikiness": peak_count / total if total > 0 else 0,
            }
        )

    spike_df = pd.DataFrame(rows).sort_values("spikiness", ascending=False)

    print("=" * 70)
    print("ANALYSIS 3: Spikiest Entities (peak month fraction of lifetime posts)")
    print("=" * 70)
    print("\nTop 20 Spikiest Entities (from top-50 by total posts):")
    print(
        f"{'Entity':<35} {'Total Posts':>12} {'Peak Month':<12}"
        f" {'Peak Posts':>12} {'Spikiness':>10}"
    )
    print("-" * 85)
    for _, r in spike_df.head(20).iterrows():
        print(
            f"{r['entity']:<35} {r['total_posts']:>12,.0f}"
            f" {r['peak_month'].strftime('%Y-%m'):<12}"
            f" {r['peak_count']:>12,.0f}"
            f" {r['spikiness']:>10.1%}"
        )


if __name__ == "__main__":
    main()
