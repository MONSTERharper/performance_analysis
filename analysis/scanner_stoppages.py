"""Scanner stoppage analysis across all databases."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from tabulate import tabulate

from db.connection import get_client

STOPPAGE_COLLECTIONS = [
    ("local_analytics_db", "scanner_stoppages"),
    ("local_analytics_db", "scanner_stoppages_summary"),
    ("test_db2", "scanner_stoppages"),
    ("test_db3", "scanner_stoppages"),
]


def _load_stoppages(db_name: str, coll_name: str) -> pd.DataFrame:
    client = get_client()
    docs = list(client[db_name][coll_name].find())
    if not docs:
        return pd.DataFrame()
    df = pd.DataFrame(docs)
    df["_source_db"] = db_name
    df["_source_collection"] = coll_name
    return df


def load_all_stoppages() -> pd.DataFrame:
    frames = []
    for db_name, coll_name in STOPPAGE_COLLECTIONS:
        df = _load_stoppages(db_name, coll_name)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def summarize_by_site(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "site" not in df.columns:
        return pd.DataFrame()

    summary = (
        df.groupby("site", dropna=False)
        .size()
        .reset_index(name="stoppage_count")
    )

    if "diff" in df.columns:
        diff_stats = (
            df.groupby("site", dropna=False)["diff"]
            .agg(mean="mean", median="median", max="max")
            .reset_index()
        )
        summary = summary.merge(diff_stats, on="site", how="left")

    if "total_time" in df.columns:
        time_stats = (
            df.groupby("site", dropna=False)["total_time"]
            .agg(mean="mean", sum="sum")
            .reset_index()
            .rename(columns={"mean": "total_time_mean", "sum": "total_time_sum"})
        )
        summary = summary.merge(time_stats, on="site", how="left")

    return summary.sort_values("stoppage_count", ascending=False)


def summarize_by_error(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    error_col = "error" if "error" in df.columns else "index"
    if error_col not in df.columns:
        return pd.DataFrame()

    summary = (
        df.groupby(error_col, dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    summary[error_col] = summary[error_col].fillna("(no error)")
    return summary.head(30)


def summarize_by_cluster(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "cluster" not in df.columns:
        return pd.DataFrame()

    return (
        df.groupby("cluster", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )


def run_analysis(output_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    df = load_all_stoppages()
    results = {
        "raw": df,
        "by_site": summarize_by_site(df),
        "by_error": summarize_by_error(df),
        "by_cluster": summarize_by_cluster(df),
    }

    print("\n=== Scanner Stoppages ===\n")
    print(f"Total records: {len(df):,}")

    if not results["by_site"].empty:
        print("\nTop sites by stoppage count:")
        print(tabulate(results["by_site"].head(15), headers="keys", tablefmt="simple", showindex=False))

    if not results["by_error"].empty:
        print("\nTop errors:")
        print(tabulate(results["by_error"].head(15), headers="keys", tablefmt="simple", showindex=False))

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in results.items():
            if not frame.empty:
                frame.to_csv(output_dir / f"stoppages_{name}.csv", index=False)

    return results
