"""Keep LLM requests within Ollama context limits."""

from __future__ import annotations

import json
from copy import deepcopy

# Rough chars-per-token for English-ish text (conservative).
CHARS_PER_TOKEN = 3.5

MAX_HISTORY_MESSAGES = 6
MAX_TOOL_CONTENT_CHARS = 2_000
MAX_ASSISTANT_CONTENT_CHARS = 1_500


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


def system_prompt_budget_tokens(num_ctx: int, *, aggressive: bool) -> int:
    """Token budget for the system prompt, derived from the model's context window.

    Leaves headroom for tool definitions, chat history, and the model's response.
    `aggressive` is the tighter budget used when a first attempt overflowed.
    """
    num_ctx = max(1, num_ctx)
    fraction = 0.25 if aggressive else 0.45
    floor = 400 if aggressive else 800
    # Never let the "budget" exceed the window itself.
    return max(min(floor, num_ctx), int(num_ctx * fraction))


def _truncate(text: str, limit: int, suffix: str = "\n…[truncated]") -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))] + suffix


def _compact_tool_content(content: str) -> str:
    if len(content) <= MAX_TOOL_CONTENT_CHARS:
        return content
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return _truncate(content, MAX_TOOL_CONTENT_CHARS)

    if isinstance(data, dict):
        if "documents" in data and isinstance(data["documents"], list):
            docs = data["documents"]
            data["documents"] = docs[:10]
            data["_truncated_for_context"] = f"showing 10 of {len(docs)} documents"
        elif "results" in data and isinstance(data["results"], list):
            rows = data["results"]
            data["results"] = rows[:15]
            data["_truncated_for_context"] = f"showing 15 of {len(rows)} rows"
    return _truncate(json.dumps(data, default=str), MAX_TOOL_CONTENT_CHARS)


def trim_messages_for_llm(messages: list[dict]) -> list[dict]:
    """Drop old turns and shrink tool payloads before sending to the model."""
    recent = messages[-MAX_HISTORY_MESSAGES:] if len(messages) > MAX_HISTORY_MESSAGES else messages
    trimmed: list[dict] = []
    for msg in recent:
        item = deepcopy(msg)
        role = item.get("role")
        if role == "tool" and isinstance(item.get("content"), str):
            item["content"] = _compact_tool_content(item["content"])
        elif role == "assistant" and isinstance(item.get("content"), str):
            item["content"] = _truncate(item["content"], MAX_ASSISTANT_CONTENT_CHARS)
        trimmed.append(item)
    return trimmed


def shrink_system_prompt(prompt: str, *, max_tokens: int) -> str:
    """Progressively shorten an oversized system prompt."""
    budget_chars = int(max_tokens * CHARS_PER_TOKEN)
    if len(prompt) <= budget_chars:
        return prompt

    # Drop everything after the RAG/schema divider, keep instructions only.
    if "\n---\n" in prompt:
        head = prompt.split("\n---\n", 1)[0]
        if len(head) <= budget_chars:
            return head + "\n\n---\n\n> Schema context omitted to fit model context window."

    return _truncate(prompt, budget_chars, suffix="\n…[system prompt truncated]")
