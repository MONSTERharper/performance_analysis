"""Database and collection inventory across all analytics databases."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from tabulate import tabulate

from db.connection import get_client, list_all_collections, list_analytics_databases


def build_inventory() -> pd.DataFrame:
    client = get_client()
    rows = []

    for db_name in list_analytics_databases():
        db = client[db_name]
        for coll_name in db.list_collection_names():
            collection = db[coll_name]
            count = collection.estimated_document_count()
            sample = collection.find_one() or {}
            rows.append(
                {
                    "database": db_name,
                    "collection": coll_name,
                    "document_count": count,
                    "field_count": len(sample),
                    "sample_fields": ", ".join(list(sample.keys())[:8]),
                }
            )

    return pd.DataFrame(rows).sort_values(
        ["database", "collection"]
    ).reset_index(drop=True)


def build_field_schema(db_name: str, coll_name: str, sample_size: int = 100) -> pd.DataFrame:
    """Infer field presence across a sample of documents."""
    client = get_client()
    pipeline = [{"$sample": {"size": sample_size}}] if sample_size else []
    docs = list(client[db_name][coll_name].aggregate(pipeline)) if pipeline else []

    if not docs:
        return pd.DataFrame()

    field_counts: dict[str, int] = {}
    for doc in docs:
        for key in doc:
            field_counts[key] = field_counts.get(key, 0) + 1

    total = len(docs)
    rows = [
        {
            "field": field,
            "present_in_pct": round(count / total * 100, 1),
            "present_count": count,
        }
        for field, count in sorted(field_counts.items(), key=lambda x: -x[1])
    ]
    return pd.DataFrame(rows)


def print_inventory(df: pd.DataFrame) -> None:
    print("\n=== MongoDB Inventory ===\n")
    print(
        tabulate(
            df,
            headers="keys",
            tablefmt="simple",
            showindex=False,
        )
    )
    print(f"\nTotal collections: {len(df)}")
    print(f"Total documents (estimated): {df['document_count'].sum():,}")


def save_inventory(df: pd.DataFrame, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "inventory.csv"
    df.to_csv(path, index=False)
    return path


def save_all_schemas(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for db_name, coll_name in list_all_collections():
        schema = build_field_schema(db_name, coll_name)
        if schema.empty:
            continue
        path = output_dir / f"schema_{db_name}_{coll_name}.csv"
        schema.to_csv(path, index=False)
        saved.append(path)
    return saved
