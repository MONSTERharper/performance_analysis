"""Format MongoDB tool output as the user-visible answer — no LLM paraphrase."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

MAX_TABLE_ROWS = 25


def _table_markdown(rows: list[dict], max_rows: int = MAX_TABLE_ROWS) -> str:
    if not rows:
        return "_No rows returned._"
    df = pd.DataFrame(rows)
    view = df.head(max_rows)
    lines = ["| " + " | ".join(str(c) for c in view.columns) + " |"]
    lines.append("| " + " | ".join("---" for _ in view.columns) + " |")
    for _, row in view.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in view.columns) + " |")
    if len(df) > max_rows:
        lines.append(f"\n_Showing {max_rows} of {len(df)} rows._")
    return "\n".join(lines)


def _format_aggregate(data: dict) -> str | None:
    rows = data.get("results") or []
    if not rows:
        return None
    normalized = []
    for row in rows:
        item = dict(row)
        if "_id" in item and len(item) <= 3:
            item = {**item}
            oid = item.pop("_id")
            if isinstance(oid, dict):
                for key, value in oid.items():
                    item.setdefault(key, value)
            else:
                item.setdefault("group", oid)
        normalized.append(item)
    collection = data.get("collection", "collection")
    return f"**{collection}** — aggregation ({len(rows)} row(s)):\n\n{_table_markdown(normalized)}"


def _format_documents(data: dict, label: str) -> str | None:
    docs = data.get("documents") or []
    if not docs:
        return None
    collection = data.get("collection", "collection")
    total = data.get("total_matching", len(docs))
    returned = data.get("returned", len(docs))
    truncated = data.get("truncated", total > returned)
    note = f"**{collection}** — {returned} row(s)"
    if truncated:
        note += f" (of {total} matching)"
    note += f":\n\n{_table_markdown(docs)}"
    return note


def _format_one(tool_name: str, data: dict) -> str | None:
    if data.get("error"):
        return f"**{tool_name}:** {data['error']}"

    if tool_name == "aggregate":
        return _format_aggregate(data)
    if tool_name in ("find_documents", "fetch_raw_data"):
        return _format_documents(data, tool_name)
    if tool_name == "count_documents":
        count = data.get("count")
        if count is None:
            return None
        collection = data.get("collection", "collection")
        return f"**{collection}** — count: **{count:,}**"
    if tool_name == "list_collections":
        rows = data.get("collections") or []
        if not rows:
            return None
        return f"**Collections in {data.get('database', 'test_db2')}:**\n\n{_table_markdown(rows)}"
    if tool_name == "describe_collection":
        fields = data.get("fields") or []
        count = data.get("document_count", "?")
        collection = data.get("collection", "collection")
        sample = data.get("sample_document") or {}
        lines = [
            f"**{collection}** — {count:,} documents",
            f"Fields: `{', '.join(fields)}`",
        ]
        if sample:
            lines.append(
                f"\nSample document:\n\n```json\n{json.dumps(sample, indent=2, default=str)}\n```"
            )
        return "\n".join(lines)
    return None


def extract_raw_payload(tool_results: list[tuple[str, dict]]) -> tuple[list[dict] | None, dict | None]:
    """Best-effort raw_data for exports from tool results."""
    for tool_name, data in reversed(tool_results):
        if data.get("error"):
            continue
        if tool_name == "aggregate":
            rows = data.get("results") or []
            if rows:
                return rows, {
                    "collection": data.get("collection"),
                    "returned": len(rows),
                    "total_matching": len(rows),
                    "truncated": False,
                    "filter": data.get("pipeline"),
                }
        if tool_name in ("find_documents", "fetch_raw_data"):
            docs = data.get("documents") or []
            if docs:
                return docs, {
                    "collection": data.get("collection"),
                    "returned": data.get("returned", len(docs)),
                    "total_matching": data.get("total_matching", len(docs)),
                    "truncated": data.get("truncated", False),
                    "filter": data.get("filter"),
                }
    return None, None


def format_grounded_answer(tool_results: list[tuple[str, dict]]) -> str | None:
    """Build answer text only from tool JSON. Returns None if nothing to show."""
    sections: list[str] = []
    for tool_name, data in tool_results:
        section = _format_one(tool_name, data)
        if section:
            sections.append(section)

    if not sections:
        return None

    header = (
        "_Answer generated directly from MongoDB query results "
        "(values are not paraphrased by the language model)._"
    )
    return header + "\n\n" + "\n\n".join(sections)


def has_groundable_data(tool_results: list[tuple[str, dict]]) -> bool:
    for tool_name, data in tool_results:
        if data.get("error"):
            continue
        if tool_name == "aggregate" and data.get("results"):
            return True
        if tool_name in ("find_documents", "fetch_raw_data") and data.get("documents"):
            return True
        if tool_name == "count_documents" and data.get("count") is not None:
            return True
        if tool_name == "list_collections" and data.get("collections"):
            return True
        if tool_name == "describe_collection" and data.get("fields"):
            return True
    return False
