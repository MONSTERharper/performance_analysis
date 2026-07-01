"""Export any collection to CSV/JSON for further analysis."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from db.connection import get_client, list_all_collections


def _serialize_doc(doc: dict) -> dict:
    result = {}
    for key, value in doc.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        elif key == "_id":
            result[key] = str(value)
        else:
            result[key] = value
    return result


def export_collection(
    db_name: str,
    coll_name: str,
    output_dir: Path,
    fmt: str = "csv",
    limit: int | None = None,
) -> Path | None:
    client = get_client()
    cursor = client[db_name][coll_name].find()
    if limit:
        cursor = cursor.limit(limit)

    docs = [_serialize_doc(doc) for doc in cursor]
    if not docs:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{db_name}_{coll_name}"

    if fmt == "json":
        path = output_dir / f"{safe_name}.json"
        with open(path, "w") as f:
            json.dump(docs, f, indent=2, default=str)
    else:
        path = output_dir / f"{safe_name}.csv"
        pd.DataFrame(docs).to_csv(path, index=False)

    return path


def export_all_collections(output_dir: Path, fmt: str = "csv") -> list[Path]:
    saved = []
    for db_name, coll_name in list_all_collections():
        path = export_collection(db_name, coll_name, output_dir, fmt=fmt)
        if path:
            saved.append(path)
            print(f"  Exported {db_name}.{coll_name} -> {path.name}")
    return saved
