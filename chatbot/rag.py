"""RAG retrieval over test_db2 knowledge base (markdown + JSON schema)."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
CONTEXT_FILE = KNOWLEDGE_DIR / "test_db2_context.md"
SCHEMA_FILE = KNOWLEDGE_DIR / "test_db2_schema.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))

# Always sent — small sections every query needs
CORE_CHUNK_IDS = {
    "core-overview",
    "core-join-keys",
    "core-notes",
}

# Intent keywords → topic tags for boosting
INTENT_KEYWORDS: dict[str, list[str]] = {
    "plot": ["plot", "chart", "graph", "visualiz", "trend", "bar", "line", "day-wise", "weekly"],
    "raw_data": ["raw", "table", "export", "csv", "spreadsheet", "records", "show me the data"],
    "error": ["error", "fault", "failure", "stoppage", "downtime", "root cause"],
    "performance": ["load time", "duration", "regression", "scan time", "throughput", "performance"],
    "slides": ["slide", "scanned", "transfer", "reviewed", "queue"],
    "relationship": ["relate", "relationship", "connect", "join", "link", "how does"],
}

COLLECTION_ALIASES: dict[str, str] = {
    "stoppage": "scanner_stoppages",
    "stoppages": "scanner_stoppages",
    "downtime": "scanner_stoppages",
    "error log": "raw_error_logs",
    "error logs": "raw_error_logs",
    "errors": "Error_counts",
    "error count": "Error_counts",
    "load time": "load_time_analysis",
    "load": "load_time_analysis",
    "regression": "regression_metrics",
    "scan performance": "scan_performance_log_statistics_detailed",
    "scanner config": "scanner_config",
    "configuration": "scanner_config",
    "slide count": "slide_count_values",
    "slides scanned": "slide_count_values",
    "slide totals": "slide_count_values_totals",
    "cta": "extracted_cta_logs",
    "ingestion": "ingestion_audit",
    "customer": "customers",
    "site": "sites",
    "scanner": "scanners",
}


@dataclass
class KnowledgeChunk:
    id: str
    title: str
    content: str
    collections: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    source: str = "md"


@dataclass
class RetrievalResult:
    chunks: list[KnowledgeChunk]
    scores: dict[str, float]
    query_collections: list[str]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _split_markdown_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (title, body) by ## and ### headers."""
    sections: list[tuple[str, str]] = []
    current_title = "intro"
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## ") or line.startswith("### "):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))
    return sections


def _extract_collection_from_title(title: str) -> str | None:
    match = re.search(r"`([a-zA-Z0-9_]+)`", title)
    if match:
        return match.group(1)
    match = re.search(r"6\.\d+\s+`?([a-zA-Z0-9_]+)`?", title)
    if match:
        return match.group(1)
    return None


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:60] or "section"


def _detect_collections_in_query(query: str) -> list[str]:
    q = query.lower()
    found: set[str] = set()
    schema = _load_schema()
    for coll in schema.get("collections", {}):
        if coll.lower() in q or coll.replace("_", " ") in q:
            found.add(coll)
    for alias, coll in COLLECTION_ALIASES.items():
        if alias in q:
            found.add(coll)
    return list(found)


def _detect_intents(query: str) -> list[str]:
    q = query.lower()
    intents = []
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            intents.append(intent)
    return intents


def build_knowledge_chunks() -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []

    md_text = CONTEXT_FILE.read_text(encoding="utf-8")
    for title, body in _split_markdown_sections(md_text):
        if not body.strip():
            continue
        coll = _extract_collection_from_title(title)
        chunk_id = _slug(title)
        topics: list[str] = []

        if coll:
            topics.append("collection")
        if "relationship" in title.lower():
            topics.append("relationship")
        if "example" in title.lower() or "query" in title.lower():
            topics.append("examples")
        if "glossary" in title.lower():
            topics.append("glossary")
        if "join key" in title.lower() or title.startswith("3."):
            topics.append("core")
            chunk_id = "core-join-keys"
        if title.startswith("1."):
            topics.append("core")
            chunk_id = "core-overview"
        if title.startswith("9."):
            topics.append("core")
            chunk_id = "core-notes"

        chunks.append(KnowledgeChunk(
            id=chunk_id,
            title=title,
            content=f"## {title}\n\n{body}",
            collections=[coll] if coll else [],
            topics=topics,
            source="md",
        ))

    schema = _load_schema()
    for coll_name, meta in schema.get("collections", {}).items():
        chunks.append(KnowledgeChunk(
            id=f"json-{coll_name}",
            title=f"Schema: {coll_name}",
            content=(
                f"Collection `{coll_name}`\n"
                f"- Purpose: {meta.get('purpose')}\n"
                f"- Documents: ~{meta.get('doc_count'):,}\n"
                f"- Join keys: {', '.join(meta.get('join_keys', []))}\n"
                f"- Links to: {', '.join(meta.get('links_to', []))}"
            ),
            collections=[coll_name],
            topics=["collection", "schema"],
            source="json",
        ))

    rel_lines = ["## Collection Relationships (structured)\n"]
    for rel in schema.get("relationships", []):
        rel_lines.append(f"- {rel['from']} → {rel['to']}: {rel['join']}")
    chunks.append(KnowledgeChunk(
        id="json-relationships",
        title="Schema relationships",
        content="\n".join(rel_lines),
        topics=["relationship", "schema"],
        source="json",
    ))

    return chunks


@lru_cache(maxsize=1)
def get_index() -> tuple[list[KnowledgeChunk], dict[str, int], float]:
    """Return (chunks, document_frequency, avg_doc_length)."""
    chunks = build_knowledge_chunks()
    df: dict[str, int] = {}
    lengths: list[int] = []

    for chunk in chunks:
        tokens = set(_tokenize(chunk.content))
        lengths.append(len(tokens))
        for t in tokens:
            df[t] = df.get(t, 0) + 1

    avg_dl = sum(lengths) / max(len(lengths), 1)
    return chunks, df, avg_dl


def _bm25_score(query_tokens: list[str], chunk: KnowledgeChunk, df: dict[str, int], avg_dl: float, n_docs: int) -> float:
    chunk_tokens = _tokenize(chunk.content)
    if not chunk_tokens:
        return 0.0
    dl = len(chunk_tokens)
    tf_map: dict[str, int] = {}
    for t in chunk_tokens:
        tf_map[t] = tf_map.get(t, 0) + 1

    k1, b = 1.5, 0.75
    score = 0.0
    for qt in set(query_tokens):
        if qt not in tf_map:
            continue
        tf = tf_map[qt]
        idf = math.log((n_docs - df.get(qt, 0) + 0.5) / (df.get(qt, 0) + 0.5) + 1)
        denom = tf + k1 * (1 - b + b * dl / avg_dl)
        score += idf * (tf * (k1 + 1)) / denom
    return score


def retrieve(query: str, top_k: int = 5) -> RetrievalResult:
    """
    Retrieve the most relevant knowledge chunks for a user query.
    Always includes small core chunks (join keys, overview, notes).
    """
    chunks, df, avg_dl = get_index()
    query_tokens = _tokenize(query)
    query_collections = _detect_collections_in_query(query)
    intents = _detect_intents(query)
    n_docs = len(chunks)

    scores: dict[str, float] = {}
    for chunk in chunks:
        score = _bm25_score(query_tokens, chunk, df, avg_dl, n_docs)

        for coll in query_collections:
            if coll in chunk.collections or coll.lower() in chunk.content.lower():
                score += 8.0

        for intent in intents:
            if intent in chunk.topics:
                score += 3.0
            if intent == "plot" and "examples" in chunk.topics:
                score += 2.0
            if intent == "raw_data" and "collection" in chunk.topics:
                score += 2.0

        if chunk.id in CORE_CHUNK_IDS:
            score += 100.0  # always included via separate logic

        scores[chunk.id] = score

    ranked = sorted(
        [c for c in chunks if c.id not in CORE_CHUNK_IDS],
        key=lambda c: scores.get(c.id, 0),
        reverse=True,
    )
    core = [c for c in chunks if c.id in CORE_CHUNK_IDS]
    selected = core + ranked[:top_k]

    seen: set[str] = set()
    unique: list[KnowledgeChunk] = []
    for c in selected:
        if c.id not in seen:
            seen.add(c.id)
            unique.append(c)

    return RetrievalResult(chunks=unique, scores=scores, query_collections=query_collections)


def format_retrieved_context(result: RetrievalResult) -> str:
    parts = [
        "> Retrieved context (RAG) — only sections relevant to this query.\n",
        f"> Matched collections: {', '.join(result.query_collections) or 'none detected'}\n",
    ]
    for chunk in result.chunks:
        parts.append(chunk.content)
        parts.append("\n---\n")
    return "\n".join(parts)
