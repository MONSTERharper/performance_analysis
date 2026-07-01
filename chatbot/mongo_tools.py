"""Safe MongoDB query tools for the LLM chatbot."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from chatbot.filters import QueryFilters
from chatbot.plot_executor import execute_plot_code
from db.connection import get_database

DATABASE = "test_db2"
MAX_FIND_LIMIT = 50
MAX_AGGREGATE_RESULTS = 100
MAX_RAW_LIMIT = 1000


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    if hasattr(value, "__str__") and type(value).__name__ == "ObjectId":
        return str(value)
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _db():
    return get_database(DATABASE)


def list_collections() -> dict:
    """List all collections in test_db2 with estimated document counts."""
    db = _db()
    result = []
    for name in sorted(db.list_collection_names()):
        result.append({
            "collection": name,
            "document_count": db[name].estimated_document_count(),
        })
    return {"database": DATABASE, "collections": result}


def describe_collection(collection: str) -> dict:
    """Return sample document and field list for a collection."""
    db = _db()
    if collection not in db.list_collection_names():
        return {"error": f"Collection '{collection}' not found in {DATABASE}"}

    coll = db[collection]
    sample = coll.find_one() or {}
    return {
        "collection": collection,
        "document_count": coll.estimated_document_count(),
        "fields": list(sample.keys()),
        "sample_document": _serialize(sample),
    }


def _merge_filter(user_filter: dict | None, filters: QueryFilters | None) -> dict:
    if filters and filters.is_active():
        return filters.merge_filter(user_filter)
    return dict(user_filter or {})


def _merge_pipeline(pipeline: list, filters: QueryFilters | None) -> list:
    if not filters or not filters.is_active():
        return pipeline
    mongo_f = filters.mongo_filter()
    if not mongo_f:
        return pipeline
    if pipeline and "$match" in pipeline[0]:
        pipeline = [{"$match": {**mongo_f, **pipeline[0]["$match"]}}] + pipeline[1:]
    else:
        pipeline = [{"$match": mongo_f}] + pipeline
    return pipeline


def find_documents(
    collection: str,
    filter: dict | None = None,
    projection: dict | None = None,
    sort: dict | None = None,
    limit: int = 20,
    filters: QueryFilters | None = None,
) -> dict:
    """Run a find query on a collection. Max 50 results."""
    db = _db()
    if collection not in db.list_collection_names():
        return {"error": f"Collection '{collection}' not found in {DATABASE}"}

    merged_filter = _merge_filter(filter, filters)
    limit = min(max(1, limit), MAX_FIND_LIMIT)
    cursor = db[collection].find(merged_filter, projection or None)
    if sort:
        cursor = cursor.sort(list(sort.items()))
    docs = [_serialize(d) for d in cursor.limit(limit)]
    total = db[collection].count_documents(merged_filter)

    return {
        "collection": collection,
        "filter": merged_filter,
        "returned": len(docs),
        "total_matching": total,
        "documents": docs,
    }


def count_documents(
    collection: str,
    filter: dict | None = None,
    filters: QueryFilters | None = None,
) -> dict:
    """Count documents matching a filter."""
    db = _db()
    if collection not in db.list_collection_names():
        return {"error": f"Collection '{collection}' not found in {DATABASE}"}

    merged_filter = _merge_filter(filter, filters)
    count = db[collection].count_documents(merged_filter)
    return {"collection": collection, "filter": merged_filter, "count": count}


def aggregate(
    collection: str,
    pipeline: list,
    limit: int = 50,
    filters: QueryFilters | None = None,
) -> dict:
    """Run an aggregation pipeline. Results capped at 100."""
    db = _db()
    if collection not in db.list_collection_names():
        return {"error": f"Collection '{collection}' not found in {DATABASE}"}

    limit = min(max(1, limit), MAX_AGGREGATE_RESULTS)
    pipeline = _merge_pipeline(list(pipeline), filters)
    if not any("$limit" in stage for stage in pipeline):
        pipeline = pipeline + [{"$limit": limit}]

    results = [_serialize(r) for r in db[collection].aggregate(pipeline)]
    return {
        "collection": collection,
        "pipeline": pipeline,
        "returned": len(results),
        "results": results,
    }


def fetch_raw_data(
    collection: str,
    filter: dict | None = None,
    projection: dict | None = None,
    sort: dict | None = None,
    limit: int = 500,
    filters: QueryFilters | None = None,
) -> dict:
    """
    Fetch raw tabular data for display and export.
    Use when user asks for raw data, table, spreadsheet, or full records.
    Max 1000 rows.
    """
    db = _db()
    if collection not in db.list_collection_names():
        return {"error": f"Collection '{collection}' not found in {DATABASE}"}

    merged_filter = _merge_filter(filter, filters)
    limit = min(max(1, limit), MAX_RAW_LIMIT)
    cursor = db[collection].find(merged_filter, projection or None)
    if sort:
        cursor = cursor.sort(list(sort.items()))
    docs = [_serialize(d) for d in cursor.limit(limit)]
    total = db[collection].count_documents(merged_filter)

    return {
        "success": True,
        "collection": collection,
        "filter": merged_filter,
        "returned": len(docs),
        "total_matching": total,
        "truncated": total > len(docs),
        "documents": docs,
    }


def generate_plot(code: str) -> dict:
    """
    Execute Python code to query MongoDB and build a Plotly chart.
    Code must assign a Plotly figure to variable `fig`.
    Available: pd, px, go, datetime, timedelta, get_database(), DATABASE.
    """
    return execute_plot_code(code)


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "list_collections",
            "description": "List all collections in test_db2 with document counts.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_collection",
            "description": "Get field names, document count, and a sample document for a collection.",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {"type": "string", "description": "Collection name"},
                },
                "required": ["collection"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_documents",
            "description": "Query documents from a collection. Max 50 results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {"type": "string"},
                    "filter": {
                        "type": "object",
                        "description": "MongoDB filter query, e.g. {\"site_key\": \"stanford--stanford--001\"}",
                    },
                    "projection": {
                        "type": "object",
                        "description": "Fields to include/exclude, e.g. {\"site\": 1, \"error\": 1}",
                    },
                    "sort": {
                        "type": "object",
                        "description": "Sort order, e.g. {\"date_str\": -1}",
                    },
                    "limit": {"type": "integer", "description": "Max results (default 20, max 50)"},
                },
                "required": ["collection"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_documents",
            "description": "Count documents matching a filter in a collection.",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {"type": "string"},
                    "filter": {"type": "object", "description": "MongoDB filter query"},
                },
                "required": ["collection"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate",
            "description": "Run a MongoDB aggregation pipeline. Max 100 results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {"type": "string"},
                    "pipeline": {
                        "type": "array",
                        "description": "Aggregation pipeline stages",
                        "items": {"type": "object"},
                    },
                    "limit": {"type": "integer", "description": "Max results (default 50, max 100)"},
                },
                "required": ["collection", "pipeline"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_raw_data",
            "description": (
                "Fetch raw tabular data for display and download. "
                "Use when the user asks for raw data, a table, records, spreadsheet, "
                "or 'show me the data'. Returns up to 1000 rows. "
                "Respects active site/date sidebar filters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {"type": "string"},
                    "filter": {"type": "object", "description": "MongoDB filter query"},
                    "projection": {"type": "object", "description": "Fields to include/exclude"},
                    "sort": {"type": "object", "description": "Sort order, e.g. {\"date_str\": -1}"},
                    "limit": {"type": "integer", "description": "Max rows (default 500, max 1000)"},
                },
                "required": ["collection"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_plot",
            "description": (
                "Generate a Plotly chart by running Python analysis code. "
                "Use when the user asks for plots, charts, trends, or visualizations. "
                "Code must assign a Plotly figure to variable `fig`. "
                "Available: pd, px, go, datetime, timedelta, get_database(), DATABASE ('test_db2')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code that queries MongoDB and assigns a Plotly figure to `fig`",
                    },
                },
                "required": ["code"],
            },
        },
    },
]


def execute_tool(name: str, arguments: dict, filters: QueryFilters | None = None) -> str:
    """Execute a tool by name and return JSON string result."""
    tools = {
        "list_collections": list_collections,
        "describe_collection": describe_collection,
        "find_documents": find_documents,
        "count_documents": count_documents,
        "aggregate": aggregate,
        "fetch_raw_data": fetch_raw_data,
        "generate_plot": generate_plot,
    }
    fn = tools.get(name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        if name in ("find_documents", "count_documents", "aggregate", "fetch_raw_data"):
            result = fn(**arguments, filters=filters)
        else:
            result = fn(**arguments)
        return json.dumps(result, indent=2, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
