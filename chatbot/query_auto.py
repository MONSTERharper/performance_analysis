"""Reliable built-in queries when LLM answers without calling tools."""

from __future__ import annotations

import re

import pandas as pd

from chatbot.filters import QueryFilters
from db.connection import get_database

DATABASE = "test_db2"
NORMAL_STOPPAGE_MESSAGES = ["Different Load", "No Scans"]


def _db():
    return get_database(DATABASE)


def _merge_filter(filters: QueryFilters | None, extra: dict | None = None) -> dict:
    base = dict(extra or {})
    if filters and filters.is_active():
        return filters.merge_filter(base)
    return base


def _table_markdown(df: pd.DataFrame, max_rows: int = 20) -> str:
    if df.empty:
        return "_No rows._"
    view = df.head(max_rows)
    lines = ["| " + " | ".join(view.columns) + " |"]
    lines.append("| " + " | ".join("---" for _ in view.columns) + " |")
    for _, row in view.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in view.columns) + " |")
    if len(df) > max_rows:
        lines.append(f"\n_Showing {max_rows} of {len(df)} rows._")
    return "\n".join(lines)


def query_top_errors(filters: QueryFilters | None, limit: int = 15) -> dict:
    db = _db()
    pipeline = [
        {"$match": _merge_filter(filters)},
        {"$group": {"_id": "$error", "count": {"$sum": "$count"}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
    ]
    rows = list(db.Error_counts.aggregate(pipeline))
    if not rows:
        pipeline = [
            {"$match": _merge_filter(filters)},
            {"$group": {"_id": "$errorCode", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": limit},
        ]
        rows = list(db.raw_error_logs.aggregate(pipeline))
        label = "errorCode"
    else:
        label = "error"

    if not rows:
        return {"success": False, "error": "No error data for current filters."}

    df = pd.DataFrame(rows).rename(columns={"_id": label})
    summary = f"Top **{len(df)}** errors by count (from MongoDB):\n\n{_table_markdown(df)}"
    return {
        "success": True,
        "summary": summary,
        "raw_data": df.to_dict(orient="records"),
        "raw_data_meta": {
            "collection": "Error_counts",
            "returned": len(df),
            "total_matching": len(df),
            "truncated": False,
            "filter": _merge_filter(filters),
        },
    }


def query_sites(filters: QueryFilters | None) -> dict:
    db = _db()
    query_filter = _merge_filter(filters)
    docs = list(db.sites.find(
        query_filter,
        {"site_key": 1, "site_name": 1, "customer": 1, "_id": 0},
    ).sort("site_name", 1))
    if not docs:
        return {"success": False, "error": "No sites found for current filters."}

    df = pd.DataFrame(docs)
    summary = f"**{len(df)}** site(s) in `test_db2`:\n\n{_table_markdown(df, max_rows=30)}"
    return {
        "success": True,
        "summary": summary,
        "raw_data": docs,
        "raw_data_meta": {
            "collection": "sites",
            "returned": len(docs),
            "total_matching": len(docs),
            "truncated": False,
            "filter": query_filter,
        },
    }


def query_slide_totals(filters: QueryFilters | None) -> dict:
    db = _db()
    query_filter = _merge_filter(filters)

    totals = list(db.slide_count_values_totals.find(
        query_filter,
        {"site": 1, "site_key": 1, "Specified cycle slides scanned": 1, "_id": 0},
    ))
    if totals:
        df = pd.DataFrame(totals)
        col = "Specified cycle slides scanned"
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        summary = f"Lifetime slide totals — **{len(df)}** site(s):\n\n{_table_markdown(df)}"
        return {
            "success": True,
            "summary": summary,
            "raw_data": df.to_dict(orient="records"),
            "raw_data_meta": {
                "collection": "slide_count_values_totals",
                "returned": len(df),
                "total_matching": len(df),
                "truncated": False,
                "filter": query_filter,
            },
        }

    docs = list(db.slide_count_values.find(
        query_filter,
        {"date_str": 1, "site": 1, "Specified cycle slides scanned": 1, "_id": 0},
    ))
    if not docs:
        return {"success": False, "error": "No slide count data for current filters."}

    df = pd.DataFrame(docs)
    df["slides"] = pd.to_numeric(df["Specified cycle slides scanned"], errors="coerce").fillna(0)
    by_site = (
        df.groupby(["site"], as_index=False)["slides"]
        .sum()
        .sort_values("slides", ascending=False)
        .rename(columns={"slides": "total_slides"})
    )
    total = int(by_site["total_slides"].sum())
    summary = (
        f"**{total:,}** slides scanned across **{len(by_site)}** site(s) "
        f"(summed from `slide_count_values`):\n\n{_table_markdown(by_site)}"
    )
    return {
        "success": True,
        "summary": summary,
        "raw_data": by_site.to_dict(orient="records"),
        "raw_data_meta": {
            "collection": "slide_count_values",
            "returned": len(by_site),
            "total_matching": len(by_site),
            "truncated": False,
            "filter": query_filter,
        },
    }


def query_stoppages_by_site(filters: QueryFilters | None, limit: int = 15) -> dict:
    db = _db()
    query_filter = _merge_filter(
        filters,
        {"message": {"$nin": NORMAL_STOPPAGE_MESSAGES}},
    )
    pipeline = [
        {"$match": query_filter},
        {"$group": {"_id": "$site", "stoppages": {"$sum": 1}, "downtime_sec": {"$sum": "$diff"}}},
        {"$sort": {"stoppages": -1}},
        {"$limit": limit},
    ]
    rows = list(db.scanner_stoppages.aggregate(pipeline))
    if not rows:
        return {"success": False, "error": "No stoppage data for current filters."}

    df = pd.DataFrame(rows).rename(columns={"_id": "site"})
    df["downtime_sec"] = pd.to_numeric(df["downtime_sec"], errors="coerce").fillna(0).round(1)
    summary = (
        f"Top **{len(df)}** sites by stoppage count "
        f"(excluding normal load gaps):\n\n{_table_markdown(df)}"
    )
    return {
        "success": True,
        "summary": summary,
        "raw_data": df.to_dict(orient="records"),
        "raw_data_meta": {
            "collection": "scanner_stoppages",
            "returned": len(df),
            "total_matching": len(df),
            "truncated": False,
            "filter": query_filter,
        },
    }


def query_load_time_by_site(filters: QueryFilters | None) -> dict:
    db = _db()
    pipeline = [
        {"$match": _merge_filter(filters)},
        {
            "$group": {
                "_id": "$site",
                "avg_duration_sec": {"$avg": "$duration_seconds"},
                "loads": {"$sum": 1},
            }
        },
        {"$sort": {"avg_duration_sec": -1}},
    ]
    rows = list(db.load_time_analysis.aggregate(pipeline))
    if not rows:
        return {"success": False, "error": "No load time data for current filters."}

    df = pd.DataFrame(rows).rename(columns={"_id": "site"})
    df["avg_duration_sec"] = pd.to_numeric(df["avg_duration_sec"], errors="coerce").round(2)
    summary = f"Average load duration by site:\n\n{_table_markdown(df)}"
    return {
        "success": True,
        "summary": summary,
        "raw_data": df.to_dict(orient="records"),
        "raw_data_meta": {
            "collection": "load_time_analysis",
            "returned": len(df),
            "total_matching": len(df),
            "truncated": False,
            "filter": _merge_filter(filters),
        },
    }


def query_collections() -> dict:
    db = _db()
    rows = []
    for name in sorted(db.list_collection_names()):
        rows.append({"collection": name, "document_count": db[name].estimated_document_count()})
    df = pd.DataFrame(rows)
    summary = f"**{len(df)}** collections in `test_db2`:\n\n{_table_markdown(df, max_rows=30)}"
    return {
        "success": True,
        "summary": summary,
        "raw_data": rows,
        "raw_data_meta": {
            "collection": "(all)",
            "returned": len(rows),
            "total_matching": len(rows),
            "truncated": False,
            "filter": {},
        },
    }


def query_errors_matching(
    filters: QueryFilters | None,
    *,
    text: str | None = None,
    limit: int = 20,
) -> dict:
    """Aggregate errors, optionally filtered by substring in error message."""
    db = _db()
    match = _merge_filter(filters)
    if text:
        match = {**match, "error": {"$regex": re.escape(text), "$options": "i"}}

    pipeline = [
        {"$match": match},
        {"$group": {"_id": "$error", "count": {"$sum": "$count"}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
    ]
    rows = list(db.Error_counts.aggregate(pipeline))
    if not rows:
        err_filter = _merge_filter(filters)
        if text:
            err_filter = {
                **err_filter,
                "$or": [
                    {"errorCode": {"$regex": re.escape(text), "$options": "i"}},
                    {"errorRootCause": {"$regex": re.escape(text), "$options": "i"}},
                ],
            }
        pipeline = [
            {"$match": err_filter},
            {"$group": {"_id": "$errorCode", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": limit},
        ]
        rows = list(db.raw_error_logs.aggregate(pipeline))
        label = "errorCode"
    else:
        label = "error"

    if not rows:
        return {"success": False, "error": f"No errors matching {text!r} for current filters."}

    df = pd.DataFrame(rows).rename(columns={"_id": label})
    summary = f"Errors matching **{text}** — top **{len(df)}** (from MongoDB):\n\n{_table_markdown(df)}"
    return {
        "success": True,
        "summary": summary,
        "raw_data": df.to_dict(orient="records"),
        "raw_data_meta": {
            "collection": "Error_counts",
            "returned": len(df),
            "total_matching": len(df),
            "truncated": False,
            "filter": match,
        },
    }


def try_auto_query(query: str, filters: QueryFilters | None) -> dict:
    """Run a built-in MongoDB query matched from the user question."""
    q = query.lower()

    if re.search(r"\b(collection|collections)\b", q) and re.search(
        r"\b(list|show|what|which|name)\b", q
    ):
        return query_collections()
    if re.search(r"\b(site|sites|customer)\b", q) and re.search(
        r"\b(list|show|which|all|name)\b", q
    ):
        return query_sites(filters)
    if re.search(r"\b(error|errors)\b", q) and re.search(r"\b(top|most|frequent|common)\b", q):
        return query_top_errors(filters)
    if re.search(r"\b(error|errors)\b", q) and re.search(r"controller", q):
        return query_errors_matching(filters, text="controller")
    if re.search(r"\b(error|errors)\b", q):
        return query_top_errors(filters)
    if re.search(r"\b(slide|slides|scanned)\b", q) and re.search(
        r"\b(how many|count|total|most|top)\b", q
    ):
        return query_slide_totals(filters)
    if re.search(r"\b(stoppage|stoppages|downtime)\b", q):
        return query_stoppages_by_site(filters)
    if re.search(r"\b(load time|load duration|duration)\b", q) and re.search(
        r"\b(average|avg|by site|per site)\b", q
    ):
        return query_load_time_by_site(filters)

    return {"success": False, "error": "No matching auto-query template."}
