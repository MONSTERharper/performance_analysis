"""Status phases emitted during chat for Streamlit UI updates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

Phase = Literal[
    "warming_model",
    "loading_model",
    "retrieving_context",
    "thinking",
    "querying_database",
    "fetching_data",
    "generating_plot",
    "using_fallback",
    "complete",
    "error",
]

STATUS_LABELS: dict[str, str] = {
    "warming_model": "Loading model into memory (first time only): `{detail}`",
    "loading_model": "Connecting to `{detail}`...",
    "retrieving_context": "Retrieving relevant schema context (RAG)...",
    "thinking": "Thinking...",
    "querying_database": "Querying database — `{detail}`",
    "fetching_data": "Fetching raw data — `{detail}`",
    "generating_plot": "Generating plot...",
    "using_fallback": "Primary model failed — switching to `{detail}`",
    "complete": "Done",
    "error": "Error: {detail}",
}

StatusCallback = Callable[[str, str], None]


def format_status(phase: str, detail: str = "") -> str:
    template = STATUS_LABELS.get(phase, "{detail}")
    return template.format(detail=detail) if "{detail}" in template else template


@dataclass
class ChatResult:
    content: str
    model_used: str
    model_mode: str = "auto"
    tool_calls_made: list[str] = field(default_factory=list)
    figure_json: str | None = None
    raw_data: list[dict] | None = None
    raw_data_meta: dict | None = None
    rag_chunks: list[str] = field(default_factory=list)
    used_rag: bool = False
    status_log: list[str] = field(default_factory=list)
    used_fallback: bool = False
