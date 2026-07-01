"""Sites, scanners, and customers reference data analysis."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from tabulate import tabulate

from db.connection import get_client

SITE_COLLECTIONS = [
    ("local_analytics_db", "SITES"),
    ("local_analytics_db", "sites_master"),
    ("test_db2", "sites"),
    ("test_db2", "customers"),
    ("test_db2", "scanners"),
    ("local_analytics_db", "SCANNERS"),
]


def _load(db_name: str, coll_name: str) -> pd.DataFrame:
    docs = list(get_client()[db_name][coll_name].find())
    if not docs:
        return pd.DataFrame()
    df = pd.DataFrame(docs)
    df["_source_db"] = db_name
    df["_source_collection"] = coll_name
    return df


def load_all_reference_data() -> dict[str, pd.DataFrame]:
    result = {}
    for db_name, coll_name in SITE_COLLECTIONS:
        key = f"{db_name}.{coll_name}"
        df = _load(db_name, coll_name)
        if not df.empty:
            result[key] = df
    return result


def summarize_sites(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for key, df in data.items():
        if "site" in df.columns or "site_name" in df.columns:
            site_col = "site_name" if "site_name" in df.columns else "site"
            subset = df[[site_col, "_source_db", "_source_collection"]].copy()
            subset = subset.rename(columns={site_col: "site"})
            frames.append(subset)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    return combined.drop_duplicates(subset=["site"]).sort_values("site")


def summarize_scanners(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for key, df in data.items():
        if "scanner" in key.lower() or "scanner_id" in df.columns:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def run_analysis(output_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    data = load_all_reference_data()
    results = {
        "sites": summarize_sites(data),
        "scanners": summarize_scanners(data),
    }
    for key, df in data.items():
        safe_key = key.replace(".", "_")
        results[safe_key] = df

    print("\n=== Sites & Scanners Reference Data ===\n")
    for key, df in data.items():
        print(f"  {key}: {len(df):,} records")

    if not results["sites"].empty:
        print(f"\nUnique sites found: {len(results['sites'])}")
        print(tabulate(results["sites"].head(15), headers="keys", tablefmt="simple", showindex=False))

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in results.items():
            if not frame.empty:
                frame.to_csv(output_dir / f"sites_{name}.csv", index=False)

    return results
