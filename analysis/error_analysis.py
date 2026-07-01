"""Error log and error count analysis."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from tabulate import tabulate

from db.connection import get_client

ERROR_LOG_COLLECTIONS = [
    ("local_analytics_db", "raw_error_logs"),
    ("local_analytics_db", "basket_level_error_details"),
    ("test_db2", "raw_error_logs"),
    ("test_db3", "raw_error_logs"),
]

ERROR_COUNT_COLLECTIONS = [
    ("test_db2", "Error_counts"),
    ("test_db3", "Error_counts"),
]


def _load_collection(db_name: str, coll_name: str) -> pd.DataFrame:
    docs = list(get_client()[db_name][coll_name].find())
    if not docs:
        return pd.DataFrame()
    df = pd.DataFrame(docs)
    df["_source_db"] = db_name
    return df


def load_all_error_logs() -> pd.DataFrame:
    frames = [_load_collection(db, coll) for db, coll in ERROR_LOG_COLLECTIONS]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_error_counts() -> pd.DataFrame:
    frames = [_load_collection(db, coll) for db, coll in ERROR_COUNT_COLLECTIONS]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def summarize_error_codes(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "errorCode" not in df.columns:
        return pd.DataFrame()

    summary = (
        df.groupby("errorCode", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    summary["errorCode"] = summary["errorCode"].fillna("(unknown)")
    return summary.head(30)


def summarize_errors_by_site(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "site" not in df.columns:
        return pd.DataFrame()

    return (
        df.groupby("site", dropna=False)
        .size()
        .reset_index(name="error_count")
        .sort_values("error_count", ascending=False)
    )


def summarize_root_causes(df: pd.DataFrame) -> pd.DataFrame:
    col = "errorRootCause" if "errorRootCause" in df.columns else None
    if not col or df.empty:
        return pd.DataFrame()

    summary = (
        df.groupby(col, dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    summary[col] = summary[col].fillna("(unknown)")
    return summary.head(20)


def summarize_error_counts(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    group_cols = [c for c in ["site", "error"] if c in df.columns]
    if not group_cols:
        return pd.DataFrame()

    agg = {"count": "sum"} if "count" in df.columns else {"_id": "count"}
    summary = (
        df.groupby(group_cols, dropna=False)
        .agg(agg)
        .reset_index()
        .sort_values(
            "count" if "count" in df.columns else "_id",
            ascending=False,
        )
    )
    if "_id" in summary.columns:
        summary = summary.rename(columns={"_id": "total_count"})
    return summary.head(30)


def run_analysis(output_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    error_logs = load_all_error_logs()
    error_counts = load_error_counts()

    results = {
        "error_logs": error_logs,
        "error_counts": error_counts,
        "by_error_code": summarize_error_codes(error_logs),
        "by_site": summarize_errors_by_site(error_logs),
        "by_root_cause": summarize_root_causes(error_logs),
        "aggregated_counts": summarize_error_counts(error_counts),
    }

    print("\n=== Error Analysis ===\n")
    print(f"Total error log records: {len(error_logs):,}")
    print(f"Total error count records: {len(error_counts):,}")

    if not results["by_error_code"].empty:
        print("\nTop error codes:")
        print(tabulate(results["by_error_code"].head(15), headers="keys", tablefmt="simple", showindex=False))

    if not results["by_site"].empty:
        print("\nErrors by site:")
        print(tabulate(results["by_site"].head(10), headers="keys", tablefmt="simple", showindex=False))

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in results.items():
            if not frame.empty:
                frame.to_csv(output_dir / f"errors_{name}.csv", index=False)

    return results
