"""Read-only MongoDB query tools exposed to the model."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from db.connection import get_database

DATABASE = "test_db2"
MAX_LIMIT = 200
MAX_AGGREGATE_RESULTS = 200


def _db():
    return get_database(DATABASE)


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    if type(value).__name__ == "ObjectId":
        return str(value)
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def list_collections() -> dict:
    db = _db()
    return {
        "database": DATABASE,
        "collections": [
            {"collection": name, "document_count": db[name].estimated_document_count()}
            for name in sorted(db.list_collection_names())
        ],
    }


def describe_collection(collection: str) -> dict:
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


def find_documents(
    collection: str,
    filter: dict | None = None,
    projection: dict | None = None,
    sort: dict | None = None,
    limit: int = 20,
) -> dict:
    db = _db()
    if collection not in db.list_collection_names():
        return {"error": f"Collection '{collection}' not found in {DATABASE}"}
    limit = min(max(1, limit), MAX_LIMIT)
    cursor = db[collection].find(filter or {}, projection or None)
    if sort:
        cursor = cursor.sort(list(sort.items()))
    docs = [_serialize(d) for d in cursor.limit(limit)]
    return {
        "collection": collection,
        "filter": filter or {},
        "returned": len(docs),
        "total_matching": db[collection].count_documents(filter or {}),
        "documents": docs,
    }


def count_documents(collection: str, filter: dict | None = None) -> dict:
    db = _db()
    if collection not in db.list_collection_names():
        return {"error": f"Collection '{collection}' not found in {DATABASE}"}
    return {
        "collection": collection,
        "filter": filter or {},
        "count": db[collection].count_documents(filter or {}),
    }


def aggregate(collection: str, pipeline: list, limit: int = 100) -> dict:
    db = _db()
    if collection not in db.list_collection_names():
        return {"error": f"Collection '{collection}' not found in {DATABASE}"}
    limit = min(max(1, limit), MAX_AGGREGATE_RESULTS)
    pipeline = list(pipeline)
    if not any("$limit" in stage for stage in pipeline):
        pipeline = pipeline + [{"$limit": limit}]
    results = [_serialize(r) for r in db[collection].aggregate(pipeline)]
    return {"collection": collection, "returned": len(results), "results": results}


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
                "properties": {"collection": {"type": "string"}},
                "required": ["collection"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_documents",
            "description": "Query documents from a collection (max 200 results).",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {"type": "string"},
                    "filter": {"type": "object", "description": "MongoDB filter query"},
                    "projection": {"type": "object", "description": "Fields to include/exclude"},
                    "sort": {"type": "object", "description": "Sort order, e.g. {\"date_str\": -1}"},
                    "limit": {"type": "integer", "description": "Max results (default 20)"},
                },
                "required": ["collection"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_documents",
            "description": "Count documents matching a filter.",
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
            "description": "Run a MongoDB aggregation pipeline (max 200 results). Use for grouping, sums, averages, top-N.",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {"type": "string"},
                    "pipeline": {"type": "array", "items": {"type": "object"}},
                    "limit": {"type": "integer"},
                },
                "required": ["collection", "pipeline"],
            },
        },
    },
]

_TOOLS = {
    "list_collections": list_collections,
    "describe_collection": describe_collection,
    "find_documents": find_documents,
    "count_documents": count_documents,
    "aggregate": aggregate,
}


def execute_tool(name: str, arguments: dict) -> str:
    fn = _TOOLS.get(name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return json.dumps(fn(**arguments), default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
