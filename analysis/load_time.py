"""Load time and scan duration analysis."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from tabulate import tabulate

from db.connection import get_client

LOAD_TIME_COLLECTIONS = [
    ("test_db2", "load_time_analysis"),
    ("test_db3", "load_time_analysis"),
]


def load_all() -> pd.DataFrame:
    frames = []
    for db_name, coll_name in LOAD_TIME_COLLECTIONS:
        docs = list(get_client()[db_name][coll_name].find())
        if docs:
            df = pd.DataFrame(docs)
            df["_source_db"] = db_name
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def summarize_by_site(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "site" not in df.columns:
        return pd.DataFrame()

    agg: dict = {"loadIdentifier": "count"}
    if "duration_seconds" in df.columns:
        agg["duration_seconds"] = ["mean", "median", "max"]
    if "slides_scanned" in df.columns:
        agg["slides_scanned"] = ["sum", "mean"]

    summary = df.groupby("site").agg(agg).reset_index()
    summary.columns = [
        "_".join(col).strip("_") if isinstance(col, tuple) else col
        for col in summary.columns
    ]
    if "loadIdentifier_count" in summary.columns:
        summary = summary.rename(columns={"loadIdentifier_count": "load_count"})
    return summary.sort_values(
        "load_count" if "load_count" in summary.columns else summary.columns[1],
        ascending=False,
    )


def summarize_by_cluster(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "clusterId" not in df.columns:
        return pd.DataFrame()

    agg: dict = {"loadIdentifier": "count"}
    if "duration_seconds" in df.columns:
        agg["duration_seconds"] = "mean"

    summary = (
        df.groupby("clusterId")
        .agg(agg)
        .reset_index()
        .sort_values("loadIdentifier", ascending=False)
    )
    summary = summary.rename(
        columns={"loadIdentifier": "load_count", "duration_seconds": "avg_duration_sec"}
    )
    return summary.head(20)


def summarize_by_basket_type(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "basket_type" not in df.columns:
        return pd.DataFrame()

    agg: dict = {"loadIdentifier": "count"}
    if "duration_seconds" in df.columns:
        agg["duration_seconds"] = ["mean", "median"]

    summary = df.groupby("basket_type").agg(agg).reset_index()
    summary.columns = [
        "_".join(col).strip("_") if isinstance(col, tuple) else col
        for col in summary.columns
    ]
    return summary


def run_analysis(output_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    df = load_all()
    results = {
        "raw": df,
        "by_site": summarize_by_site(df),
        "by_cluster": summarize_by_cluster(df),
        "by_basket_type": summarize_by_basket_type(df),
    }

    print("\n=== Load Time Analysis ===\n")
    print(f"Total load records: {len(df):,}")

    if not results["by_site"].empty:
        print("\nLoad times by site:")
        print(tabulate(results["by_site"].head(10), headers="keys", tablefmt="simple", showindex=False))

    if not results["by_basket_type"].empty:
        print("\nBy basket type:")
        print(tabulate(results["by_basket_type"], headers="keys", tablefmt="simple", showindex=False))

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in results.items():
            if not frame.empty:
                frame.to_csv(output_dir / f"load_time_{name}.csv", index=False)

    return results
