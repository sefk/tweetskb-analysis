"""
Analysis 4: Entities with Sustained Growth or Decline

For the top 200 entities by total post count (classified, non-redacted),
fits a linear regression of monthly post_count vs a zero-based month index.
The slope (posts per month) measures the long-run trend.

Prints the 20 fastest-growing and 20 fastest-declining entities.

Note: R² is included to distinguish genuine trends from noisy slopes.
A high absolute slope with low R² may reflect a spike rather than a trend.
"""

import numpy as np
import pandas as pd

DATA_DIR = "/Users/sefk/src/stanford-dataviz/tweetskb-analysis/tweetskb_tables"
MIN_MONTHS = 6  # require at least this many months of data


def linregress(x, y):
    """Return (slope, r_squared) via numpy least-squares."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    xm, ym = x.mean(), y.mean()
    ss_xy = ((x - xm) * (y - ym)).sum()
    ss_xx = ((x - xm) ** 2).sum()
    ss_yy = ((y - ym) ** 2).sum()
    if ss_xx == 0:
        return 0.0, 0.0
    slope = ss_xy / ss_xx
    r2 = (ss_xy**2) / (ss_xx * ss_yy) if ss_yy > 0 else 0.0
    return slope, r2


def main():
    df = pd.read_parquet(f"{DATA_DIR}/entity.parquet")
    df["year_month"] = pd.to_datetime(df["year_month"], format="%Y-%m")

    clean = df[df["classified"] & ~df["redacted"]].copy()

    entity_totals = clean.groupby("entity")["post_count"].sum().nlargest(200)
    top200 = entity_totals.index.tolist()
    subset = clean[clean["entity"].isin(top200)].copy()

    # Assign a global month index (0-based from earliest month in this subset)
    all_months = sorted(subset["year_month"].unique())
    month_index = {m: i for i, m in enumerate(all_months)}
    subset["month_idx"] = subset["year_month"].map(month_index)

    rows = []
    for entity, grp in subset.groupby("entity"):
        grp_sorted = grp.sort_values("month_idx")
        if len(grp_sorted) < MIN_MONTHS:
            continue
        slope, r2 = linregress(grp_sorted["month_idx"], grp_sorted["post_count"])
        rows.append(
            {
                "entity": entity,
                "total_posts": entity_totals[entity],
                "slope": slope,
                "r_squared": r2,
                "n_months": len(grp_sorted),
            }
        )

    slope_df = pd.DataFrame(rows)

    hdr = (
        f"{'Entity':<35} {'Total Posts':>12} {'Slope (posts/mo)':>18}"
        f" {'R²':>8} {'Months':>8}"
    )
    sep = "-" * 85

    print("=" * 70)
    print("ANALYSIS 4: Entities with Sustained Growth / Decline (top 200 by posts)")
    print("=" * 70)

    print("\nTop 20 FASTEST GROWING entities:")
    print(hdr)
    print(sep)
    for _, r in slope_df.nlargest(20, "slope").iterrows():
        print(
            f"{r['entity']:<35} {r['total_posts']:>12,.0f}"
            f" {r['slope']:>18.1f} {r['r_squared']:>8.3f} {r['n_months']:>8.0f}"
        )

    print("\nTop 20 FASTEST DECLINING entities:")
    print(hdr)
    print(sep)
    for _, r in slope_df.nsmallest(20, "slope").iterrows():
        print(
            f"{r['entity']:<35} {r['total_posts']:>12,.0f}"
            f" {r['slope']:>18.1f} {r['r_squared']:>8.3f} {r['n_months']:>8.0f}"
        )


if __name__ == "__main__":
    main()
