"""
Analysis 1: Monthly Tweet Volume Over Time

Aggregates total post_count per month across all rows in date.parquet
(including unclassified rows), then prints the full time series and
flags the two known data anomalies in the TweetsKB corpus:

  - Dec 2017 – Mar 2018 : near-zero counts (source data gap)
  - Mar 2013, May 2021  : months missing entirely (corrupted gzip)
"""

import pandas as pd

DATA_DIR = "/Users/sefk/src/stanford-dataviz/tweetskb-analysis/tweetskb_tables"


def main():
    df = pd.read_parquet(f"{DATA_DIR}/date.parquet")
    df["year_month"] = pd.to_datetime(df["year_month"], format="%Y-%m")

    monthly = df.groupby("year_month")["post_count"].sum().reset_index()
    monthly = monthly.sort_values("year_month")

    gap_months = set(pd.date_range("2017-12", "2018-03", freq="MS"))
    missing_months = {pd.Timestamp("2013-03"), pd.Timestamp("2021-05")}

    print("=" * 70)
    print("ANALYSIS 1: Monthly Tweet Volume Over Time")
    print("=" * 70)
    print(f"\n{'Year-Month':<14} {'Post Count':>14}  Note")
    print("-" * 65)
    for _, row in monthly.iterrows():
        ym = row["year_month"]
        count = int(row["post_count"])
        note = ""
        if ym in gap_months:
            note = "<-- KNOWN DATA GAP (near-zero)"
        elif ym in missing_months:
            note = "<-- MISSING (corrupted gzip)"
        print(f"{ym.strftime('%Y-%m'):<14} {count:>14,}  {note}")

    print(f"\nTotal months in dataset  : {len(monthly)}")
    print(f"Total posts (all months) : {monthly['post_count'].sum():>20,.0f}")
    print(f"Median monthly posts     : {monthly['post_count'].median():>20,.0f}")
    peak_row = monthly.loc[monthly["post_count"].idxmax()]
    print(f"Peak month               : {peak_row['year_month'].strftime('%Y-%m')}  ({int(peak_row['post_count']):,})")


if __name__ == "__main__":
    main()
