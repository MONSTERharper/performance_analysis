"""Reliable built-in plots when LLM tool-calling fails."""

from __future__ import annotations

import re

import pandas as pd
import plotly.express as px
import plotly.io as pio

from chatbot.filters import QueryFilters
from db.connection import get_database

DATABASE = "test_db2"


def _db():
    return get_database(DATABASE)


def _merge_filter(filters: QueryFilters | None, extra: dict | None = None) -> dict:
    base = dict(extra or {})
    if filters and filters.is_active():
        return filters.merge_filter(base)
    return base


def _to_figure_json(fig) -> str:
    return pio.to_json(fig)


def plot_slides_daywise(filters: QueryFilters | None) -> dict:
    db = _db()
    query_filter = _merge_filter(filters)
    docs = list(db.slide_count_values.find(
        query_filter,
        {"date_str": 1, "Specified cycle slides scanned": 1, "site": 1, "_id": 0},
    ))
    if not docs:
        return {"success": False, "error": "No slide count data for current filters."}

    df = pd.DataFrame(docs)
    df["slides"] = pd.to_numeric(df["Specified cycle slides scanned"], errors="coerce").fillna(0)
    daily = df.groupby("date_str", as_index=False)["slides"].sum().sort_values("date_str")

    fig = px.line(
        daily, x="date_str", y="slides",
        title="Slides scanned per day",
        markers=True,
    )
    fig.update_layout(xaxis_title="Date", yaxis_title="Slides scanned", template="plotly_white")
    return {
        "success": True,
        "figure_json": _to_figure_json(fig),
        "summary": f"Day-wise slide counts — **{len(daily)}** days, **{int(daily['slides'].sum()):,}** total slides.",
    }


def plot_load_time_by_site(filters: QueryFilters | None) -> dict:
    db = _db()
    query_filter = _merge_filter(filters)
    docs = list(db.load_time_analysis.find(
        query_filter,
        {"site": 1, "duration_seconds": 1, "_id": 0},
    ))
    if not docs:
        return {"success": False, "error": "No load time data for current filters."}

    df = pd.DataFrame(docs)
    df["duration_seconds"] = pd.to_numeric(df["duration_seconds"], errors="coerce")
    by_site = df.groupby("site", as_index=False)["duration_seconds"].mean().sort_values(
        "duration_seconds", ascending=False
    )

    fig = px.bar(
        by_site, x="site", y="duration_seconds",
        title="Average load duration by site (seconds)",
    )
    fig.update_layout(xaxis_title="Site", yaxis_title="Avg duration (sec)", template="plotly_white")
    return {
        "success": True,
        "figure_json": _to_figure_json(fig),
        "summary": f"Average load duration across **{len(by_site)}** sites.",
    }


def plot_stoppages_by_site(filters: QueryFilters | None) -> dict:
    db = _db()
    query_filter = _merge_filter(filters, {"message": {"$nin": ["Different Load", "No Scans"]}})
    docs = list(db.scanner_stoppages.find(query_filter, {"site": 1, "_id": 0}))
    if not docs:
        return {"success": False, "error": "No stoppage data for current filters."}

    df = pd.DataFrame(docs)
    counts = df.groupby("site", as_index=False).size().rename(columns={"size": "count"})
    counts = counts.sort_values("count", ascending=False).head(20)

    fig = px.bar(counts, x="site", y="count", title="Scanner stoppages by site (excl. normal gaps)")
    fig.update_layout(xaxis_title="Site", yaxis_title="Stoppages", template="plotly_white")
    return {
        "success": True,
        "figure_json": _to_figure_json(fig),
        "summary": f"Stoppage counts for **{len(counts)}** sites (excluding normal load gaps).",
    }


def plot_top_errors(filters: QueryFilters | None, limit: int = 15) -> dict:
    db = _db()
    pipeline = [
        {"$match": _merge_filter(filters)},
        {"$group": {"_id": "$errorCode", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
    ]
    results = list(db.raw_error_logs.aggregate(pipeline))
    if not results:
        return {"success": False, "error": "No error log data for current filters."}

    df = pd.DataFrame(results).rename(columns={"_id": "errorCode"})
    fig = px.bar(df, x="errorCode", y="count", title=f"Top {limit} error codes")
    fig.update_layout(xaxis_title="Error code", yaxis_title="Count", template="plotly_white")
    return {
        "success": True,
        "figure_json": _to_figure_json(fig),
        "summary": f"Top **{len(df)}** error codes from raw error logs.",
    }


def plot_regression_trend(filters: QueryFilters | None) -> dict:
    db = _db()
    query_filter = _merge_filter(filters)
    docs = list(db.regression_metrics.find(
        query_filter,
        {"date_str": 1, "site": 1, "average_scan_time": 1, "_id": 0},
    ))
    if not docs:
        return {"success": False, "error": "No regression metrics for current filters."}

    df = pd.DataFrame(docs).sort_values("date_str")
    fig = px.line(
        df, x="date_str", y="average_scan_time", color="site",
        title="Average scan time trend", markers=True,
    )
    fig.update_layout(xaxis_title="Date", yaxis_title="Avg scan time (sec)", template="plotly_white")
    return {
        "success": True,
        "figure_json": _to_figure_json(fig),
        "summary": f"Scan time trend — **{df['site'].nunique()}** site(s), **{len(df)}** data points.",
    }


def try_auto_plot(query: str, filters: QueryFilters | None) -> dict:
    """Pick and run a built-in plot from the user query."""
    q = query.lower()

    if re.search(r"\b(slide|scanned)\b", q) and re.search(r"\b(plot|chart|graph|day|week|trend)\b", q):
        return plot_slides_daywise(filters)
    if re.search(r"\b(load time|load duration|duration)\b", q) and re.search(r"\b(plot|chart|bar)\b", q):
        return plot_load_time_by_site(filters)
    if re.search(r"\b(stoppage|downtime)\b", q) and re.search(r"\b(plot|chart|bar)\b", q):
        return plot_stoppages_by_site(filters)
    if re.search(r"\b(error|errors)\b", q) and re.search(r"\b(plot|chart|bar|top)\b", q):
        return plot_top_errors(filters)
    if re.search(r"\b(regression|scan time)\b", q) and re.search(r"\b(plot|chart|trend)\b", q):
        return plot_regression_trend(filters)

    # Generic plot request — default to slides day-wise
    if re.search(r"\b(plot|chart|graph|visualiz)\b", q):
        return plot_slides_daywise(filters)

    return {"success": False, "error": "No matching auto-plot template."}
