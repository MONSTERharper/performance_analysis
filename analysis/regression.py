"""Scan performance regression metrics analysis."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from tabulate import tabulate

from db.connection import get_client

REGRESSION_COLLECTIONS = [
    ("test_db2", "regression_metrics"),
    ("test_db3", "regression_metrics"),
]

SCAN_PERF_COLLECTIONS = [
    ("test_db2", "scan_performance_log_statistics_detailed"),
    ("test_db3", "scan_performance_log_statistics_detailed"),
    ("test_db3", "scan_performance_log_statistics_detailed_records"),
]


def _load(db_name: str, coll_name: str) -> pd.DataFrame:
    docs = list(get_client()[db_name][coll_name].find())
    if not docs:
        return pd.DataFrame()
    df = pd.DataFrame(docs)
    df["_source_db"] = db_name
    return df


def load_regression_metrics() -> pd.DataFrame:
    frames = [_load(db, coll) for db, coll in REGRESSION_COLLECTIONS]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_scan_performance() -> pd.DataFrame:
    frames = [_load(db, coll) for db, coll in SCAN_PERF_COLLECTIONS]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def summarize_regression_by_site(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "site" not in df.columns:
        return pd.DataFrame()

    numeric_cols = [
        c
        for c in [
            "average_scan_time",
            "average_scan_area",
            "median_scan_time",
            "pearson_correlation",
            "prediction_225",
        ]
        if c in df.columns
    ]
    if not numeric_cols:
        return pd.DataFrame()

    return (
        df.groupby("site")[numeric_cols]
        .mean()
        .reset_index()
        .sort_values("average_scan_time", ascending=False)
    )


def summarize_scan_performance(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "site" not in df.columns:
        return pd.DataFrame()

    agg: dict = {}
    if "records" in df.columns:
        agg["records"] = "sum"
    if "sample_count" in df.columns:
        agg["sample_count"] = "sum"

    if not agg:
        return df.groupby("site").size().reset_index(name="record_count")

    return df.groupby("site").agg(agg).reset_index()


def run_analysis(output_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    regression = load_regression_metrics()
    scan_perf = load_scan_performance()

    results = {
        "regression_raw": regression,
        "scan_perf_raw": scan_perf,
        "regression_by_site": summarize_regression_by_site(regression),
        "scan_perf_by_site": summarize_scan_performance(scan_perf),
    }

    print("\n=== Regression & Scan Performance ===\n")
    print(f"Regression metric records: {len(regression):,}")
    print(f"Scan performance records: {len(scan_perf):,}")

    if not results["regression_by_site"].empty:
        print("\nAverage scan metrics by site:")
        print(
            tabulate(
                results["regression_by_site"].head(10),
                headers="keys",
                tablefmt="simple",
                showindex=False,
            )
        )

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in results.items():
            if not frame.empty:
                frame.to_csv(output_dir / f"regression_{name}.csv", index=False)

    return results
