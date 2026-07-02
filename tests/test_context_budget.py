"""Tests for context_budget — the fix for the 4096-token overflow crash."""

from __future__ import annotations

import json

from chatbot.context_budget import (
    MAX_HISTORY_MESSAGES,
    MAX_TOOL_CONTENT_CHARS,
    estimate_tokens,
    shrink_system_prompt,
    system_prompt_budget_tokens,
    trim_messages_for_llm,
)


def test_estimate_tokens_scales_with_length():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 350) > 90


def test_trim_messages_keeps_only_recent_turns():
    messages = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
    trimmed = trim_messages_for_llm(messages)
    assert len(trimmed) == MAX_HISTORY_MESSAGES
    # Keeps the *latest* messages
    assert trimmed[-1]["content"] == "msg 19"


def test_trim_messages_compacts_large_tool_documents():
    big_docs = [{"a": i, "b": "x" * 50} for i in range(500)]
    content = json.dumps({"documents": big_docs, "collection": "scanner_stoppages"})
    messages = [{"role": "tool", "content": content}]
    trimmed = trim_messages_for_llm(messages)
    out = trimmed[0]["content"]
    assert len(out) <= MAX_TOOL_CONTENT_CHARS + 50
    data = json.loads(out.split("\n…")[0]) if "\n…" in out else json.loads(out)
    assert len(data["documents"]) <= 10
    assert "_truncated_for_context" in data


def test_trim_messages_compacts_large_aggregate_results():
    rows = [{"_id": f"err{i}", "count": i} for i in range(500)]
    content = json.dumps({"results": rows, "collection": "Error_counts"})
    trimmed = trim_messages_for_llm([{"role": "tool", "content": content}])
    out = trimmed[0]["content"]
    body = out.split("\n…")[0] if "\n…" in out else out
    data = json.loads(body)
    assert len(data["results"]) <= 15


def test_trim_messages_truncates_long_assistant_text():
    messages = [{"role": "assistant", "content": "y" * 10_000}]
    trimmed = trim_messages_for_llm(messages)
    assert len(trimmed[0]["content"]) < 2_000


def test_shrink_system_prompt_noop_when_small():
    prompt = "short instructions"
    assert shrink_system_prompt(prompt, max_tokens=1000) == prompt


def test_shrink_system_prompt_drops_schema_after_divider():
    head = "INSTRUCTIONS: be grounded."
    schema = "S" * 50_000
    prompt = f"{head}\n---\n{schema}"
    out = shrink_system_prompt(prompt, max_tokens=200)
    assert head in out
    assert "Schema context omitted" in out
    assert len(out) < len(prompt)


def test_shrink_system_prompt_hard_truncates_when_no_divider():
    prompt = "Z" * 50_000
    out = shrink_system_prompt(prompt, max_tokens=100)
    assert len(out) < 1_000


def test_budget_scales_with_context_window():
    # Larger window -> larger prompt budget.
    assert system_prompt_budget_tokens(8192, aggressive=False) > system_prompt_budget_tokens(
        4096, aggressive=False
    )
    # Aggressive budget is tighter than the normal one for the same window.
    assert system_prompt_budget_tokens(8192, aggressive=True) < system_prompt_budget_tokens(
        8192, aggressive=False
    )


def test_budget_never_exceeds_window():
    for ctx in (256, 1024, 4096, 8192):
        assert system_prompt_budget_tokens(ctx, aggressive=False) <= ctx
        assert system_prompt_budget_tokens(ctx, aggressive=True) <= ctx
