"""Load knowledge base documents for LLM system context."""

from __future__ import annotations

import json
from pathlib import Path

from chatbot.rag import format_retrieved_context, retrieve

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

CONTEXT_FILE = KNOWLEDGE_DIR / "test_db2_context.md"
SCHEMA_FILE = KNOWLEDGE_DIR / "test_db2_schema.json"

BASE_INSTRUCTIONS = """You are a performance analytics assistant for digital pathology scanner data stored in MongoDB database `test_db2`.

When users ask questions, you should:
1. Interpret the question using the schema knowledge below
2. Use the provided tools to query MongoDB when you need actual data
3. Explain results clearly with context about what the fields mean
4. Always query `test_db2` unless the user specifies otherwise
5. Use `site_key` for reliable joins, not display names
6. Filter out normal stoppages (`message: "Different Load"`, `"No Scans"`) when analyzing problems
7. State units: diff=seconds, total_time=minutes, duration_seconds=seconds, scan area=mm²

If you cannot answer from schema knowledge alone, query the database before responding.
"""


def load_context() -> str:
    """Load the full markdown context document (no RAG)."""
    if not CONTEXT_FILE.exists():
        raise FileNotFoundError(f"Knowledge file not found: {CONTEXT_FILE}")
    return CONTEXT_FILE.read_text(encoding="utf-8")


def load_schema() -> dict:
    """Load structured schema JSON."""
    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_FILE}")
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def build_system_prompt(
    query: str | None = None,
    use_rag: bool = True,
    top_k: int = 5,
) -> tuple[str, list[str]]:
    """
    Build system prompt with optional RAG retrieval.
    Returns (prompt, list of retrieved chunk titles).
    """
    chunk_titles: list[str] = []

    if use_rag and query:
        result = retrieve(query, top_k=top_k)
        context = format_retrieved_context(result)
        chunk_titles = [c.title for c in result.chunks]
    else:
        context = load_context()

    prompt = f"""{BASE_INSTRUCTIONS}

---

{context}
"""
    return prompt, chunk_titles
