"""Slide count and ingestion pipeline analysis."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from tabulate import tabulate

from db.connection import get_client

SLIDE_COUNT_COLLECTIONS = [
    ("test_db2", "slide_count_values"),
    ("test_db2", "slide_count_values_totals"),
    ("test_db3", "slide_count_values"),
    ("test_db3", "slide_count_values_totals"),
]

INGESTION_COLLECTIONS = [
    ("test_db2", "ingestion_audit"),
    ("test_db2", "ingestion_reservation"),
    ("test_db3", "ingestion_audit"),
    ("test_db3", "ingestion_reservation"),
]

CTA_LOG_COLLECTIONS = [
    ("test_db2", "extracted_cta_logs"),
    ("test_db3", "extracted_cta_logs"),
]


def _load(db_name: str, coll_name: str) -> pd.DataFrame:
    docs = list(get_client()[db_name][coll_name].find())
    if not docs:
        return pd.DataFrame()
    df = pd.DataFrame(docs)
    df["_source_db"] = db_name
    return df


def load_slide_counts() -> pd.DataFrame:
    frames = [_load(db, coll) for db, coll in SLIDE_COUNT_COLLECTIONS if "totals" not in coll]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_slide_totals() -> pd.DataFrame:
    frames = [_load(db, coll) for db, coll in SLIDE_COUNT_COLLECTIONS if "totals" in coll]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_ingestion_audit() -> pd.DataFrame:
    frames = [_load(db, coll) for db, coll in INGESTION_COLLECTIONS if "audit" in coll]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_cta_logs() -> pd.DataFrame:
    frames = [_load(db, coll) for db, coll in CTA_LOG_COLLECTIONS]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def summarize_ingestion_status(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    group_cols = [c for c in ["status", "collection_name", "site_key"] if c in df.columns]
    if not group_cols:
        return pd.DataFrame()

    return (
        df.groupby(group_cols)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )


def summarize_cta_by_level(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "level" not in df.columns:
        return pd.DataFrame()

    summary = (
        df.groupby("level", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    return summary


def summarize_cta_by_module(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "module" not in df.columns:
        return pd.DataFrame()

    return (
        df.groupby("module", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .head(20)
    )


def run_analysis(output_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    slide_counts = load_slide_counts()
    slide_totals = load_slide_totals()
    ingestion = load_ingestion_audit()
    cta_logs = load_cta_logs()

    results = {
        "slide_counts": slide_counts,
        "slide_totals": slide_totals,
        "ingestion_audit": ingestion,
        "ingestion_status": summarize_ingestion_status(ingestion),
        "cta_logs": cta_logs,
        "cta_by_level": summarize_cta_by_level(cta_logs),
        "cta_by_module": summarize_cta_by_module(cta_logs),
    }

    print("\n=== Slide Counts & Ingestion ===\n")
    print(f"Slide count records: {len(slide_counts):,}")
    print(f"Slide total records: {len(slide_totals):,}")
    print(f"Ingestion audit records: {len(ingestion):,}")
    print(f"CTA log records: {len(cta_logs):,}")

    if not results["ingestion_status"].empty:
        print("\nIngestion status breakdown:")
        print(tabulate(results["ingestion_status"].head(15), headers="keys", tablefmt="simple", showindex=False))

    if not results["cta_by_level"].empty:
        print("\nCTA logs by level:")
        print(tabulate(results["cta_by_level"], headers="keys", tablefmt="simple", showindex=False))

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in results.items():
            if not frame.empty:
                frame.to_csv(output_dir / f"slides_{name}.csv", index=False)

    return results
