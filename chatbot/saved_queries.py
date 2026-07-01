"""Persist saved queries to a JSON file."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

SAVED_QUERIES_FILE = Path(__file__).resolve().parent.parent / "data" / "saved_queries.json"


def _ensure_file() -> None:
    SAVED_QUERIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SAVED_QUERIES_FILE.exists():
        SAVED_QUERIES_FILE.write_text("[]", encoding="utf-8")


def load_queries() -> list[dict]:
    _ensure_file()
    try:
        return json.loads(SAVED_QUERIES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_query(
    query: str,
    site_key: str | None = None,
    site_name: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
) -> dict:
    queries = load_queries()
    entry = {
        "id": str(uuid.uuid4())[:8],
        "query": query.strip(),
        "site_key": site_key,
        "site_name": site_name,
        "date_start": date_start,
        "date_end": date_end,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    queries.insert(0, entry)
    SAVED_QUERIES_FILE.write_text(json.dumps(queries, indent=2), encoding="utf-8")
    return entry


def delete_query(query_id: str) -> bool:
    queries = load_queries()
    updated = [q for q in queries if q.get("id") != query_id]
    if len(updated) == len(queries):
        return False
    SAVED_QUERIES_FILE.write_text(json.dumps(updated, indent=2), encoding="utf-8")
    return True
