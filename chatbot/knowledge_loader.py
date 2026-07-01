"""Load knowledge base documents for LLM system context."""

from __future__ import annotations

import json
from pathlib import Path

from chatbot.intent import is_data_question, is_greeting_or_smalltalk
from chatbot.rag import format_retrieved_context, retrieve

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

CONTEXT_FILE = KNOWLEDGE_DIR / "test_db2_context.md"
SCHEMA_FILE = KNOWLEDGE_DIR / "test_db2_schema.json"

BASE_INSTRUCTIONS = """You are a performance analytics assistant for digital pathology scanner data stored in MongoDB database `test_db2`.

## Conversation rules (IMPORTANT)
- If the user only greets you (hi, hello, hey) or asks what you can do: reply briefly and friendly. Do NOT query the database or write MongoDB code.
- Only use tools when the user asks a **specific data question** (counts, plots, errors, sites, trends, raw data, etc.).
- NEVER invent query results, fake numbers, or paste MongoDB/Python code as a substitute for calling a tool.
- If you need real data, you MUST call a tool (`find_documents`, `aggregate`, `fetch_raw_data`, `generate_plot`, etc.) — do not guess.
- Your final answer for any data question must be grounded in tool output from this turn. If no tool ran, you do not know the answer.

## Data question rules
1. Interpret the question using the schema knowledge below
2. Use tools to query MongoDB when you need actual numbers or records
3. Explain results clearly with context about what the fields mean
4. Always query `test_db2` unless the user specifies otherwise
5. Use `site_key` for reliable joins, not display names
6. Filter out normal stoppages (`message: "Different Load"`, `"No Scans"`) when analyzing problems
7. State units: diff=seconds, total_time=minutes, duration_seconds=seconds, scan area=mm²
8. Use field `average_scan_area` (NOT scan_area_mm2) in regression_metrics
9. Respect active sidebar date filters — use those dates, not made-up years
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

    # Skip heavy RAG for greetings — avoids pulling random schema chunks
    if use_rag and query and is_data_question(query):
        result = retrieve(query, top_k=top_k)
        context = format_retrieved_context(result)
        chunk_titles = [c.title for c in result.chunks]
    elif use_rag and query and is_greeting_or_smalltalk(query):
        context = (
            "> Minimal context (greeting/small talk — no schema retrieval needed).\n"
            "Database: test_db2 — scanner performance analytics for hospital/lab sites."
        )
        chunk_titles = ["(greeting — RAG skipped)"]
    else:
        context = load_context()

    prompt = f"""{BASE_INSTRUCTIONS}

---

{context}
"""
    return prompt, chunk_titles
