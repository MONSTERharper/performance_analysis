"""Build the system prompt: schema knowledge + how to answer."""

from __future__ import annotations

from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
CONTEXT_FILE = KNOWLEDGE_DIR / "test_db2_context.md"

INSTRUCTIONS = """You are a MongoDB analytics assistant for the database `test_db2`.

To answer any question you MUST query MongoDB with the provided tools
(`list_collections`, `describe_collection`, `find_documents`, `count_documents`,
`aggregate`). Never guess or invent numbers, names, or values — only report what the
tools return. If a query returns nothing, say so.

Guidance:
- Use `aggregate` for counts, sums, averages, grouping, and top-N questions.
- Use the field `site_key` for joins/filters, not display names.
- `date_str` is a string in `YYYY-MM-DD` format.
- Keep answers concise and factual, based only on query results.

The full database schema follows. Use it to pick the right collections, fields, and filters.
"""


def build_system_prompt() -> str:
    schema = CONTEXT_FILE.read_text(encoding="utf-8")
    return f"{INSTRUCTIONS}\n\n---\n\n{schema}"
