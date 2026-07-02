"""End-to-end agent flow tests with fake Ollama + patched DB layer.

These are the regression guards for the two issues we hit:
  1. Context window overflow (8k prompt vs 4k model) must self-recover.
  2. After a real DB query, the answer must not be an LLM paraphrase.
"""

from __future__ import annotations

import json

import pytest

import chatbot.agent as agent_mod
from chatbot.agent import PerformanceChatbot
from conftest import (
    ContextOverflowError,
    FakeOllama,
    make_text_step,
    make_tool_step,
)


def _bot(steps: list) -> PerformanceChatbot:
    return PerformanceChatbot(ollama_client=FakeOllama(steps))


# --------------------------------------------------------------------------- #
# 1. Greetings never call the model
# --------------------------------------------------------------------------- #
def test_greeting_short_circuits():
    ollama = FakeOllama([])  # no steps -> any LLM call would raise
    bot = PerformanceChatbot(ollama_client=ollama)
    result = bot.chat("hi")
    assert result.model_used == "(greeting handler)"
    assert ollama.calls == []


# --------------------------------------------------------------------------- #
# 2. Known DB questions are answered by built-in query, skipping the LLM
# --------------------------------------------------------------------------- #
def test_controller_error_uses_auto_query_not_llm(monkeypatch):
    ollama = FakeOllama([])  # LLM must not be called
    monkeypatch.setattr(
        agent_mod,
        "try_auto_query",
        lambda q, f: {
            "success": True,
            "summary": "Errors matching controller ...",
            "raw_data": [{"error": "Controller comms lost", "count": 5}],
            "raw_data_meta": {"collection": "Error_counts"},
        },
    )
    bot = PerformanceChatbot(ollama_client=ollama)
    result = bot.chat("types of controller card errors", force_builtin_plots=True)

    assert result.model_used == "(auto query)"
    assert ollama.calls == []
    assert "auto_query" in result.tool_calls_made
    assert result.raw_data[0]["error"] == "Controller comms lost"


# --------------------------------------------------------------------------- #
# 3. Explicit plot request uses the built-in chart, skipping the LLM
# --------------------------------------------------------------------------- #
def test_plot_request_uses_builtin_chart(monkeypatch):
    ollama = FakeOllama([])
    monkeypatch.setattr(
        agent_mod,
        "try_auto_plot",
        lambda q, f: {"success": True, "figure_json": '{"data":[]}', "summary": "chart!"},
    )
    bot = PerformanceChatbot(ollama_client=ollama)
    result = bot.chat("plot slides day-wise", force_builtin_plots=True)

    assert result.figure_json == '{"data":[]}'
    assert result.model_used == "(built-in chart)"
    assert ollama.calls == []


# --------------------------------------------------------------------------- #
# 4. Context overflow on the first LLM call self-recovers with a trimmed prompt
# --------------------------------------------------------------------------- #
def test_context_overflow_retries_with_trimmed_prompt(monkeypatch):
    # A conceptual question -> reaches the LLM loop, needs_db is False.
    monkeypatch.setattr(agent_mod, "try_auto_query", lambda q, f: {"success": False})

    steps = [ContextOverflowError(), make_text_step("Here is a conceptual explanation.")]
    ollama = FakeOllama(steps)
    bot = PerformanceChatbot(ollama_client=ollama)

    result = bot.chat(
        "explain in detail how the ingestion pipeline is architected across collections",
        use_rag=False,
        force_builtin_plots=True,
    )

    assert result.content == "Here is a conceptual explanation."
    # two attempts were made (overflow then success)
    assert len(ollama.calls) == 2
    # the recovery attempt sent fewer/smaller messages than a full prompt
    first_len = sum(len(m.get("content") or "") for m in ollama.calls[0]["messages"])
    second_len = sum(len(m.get("content") or "") for m in ollama.calls[1]["messages"])
    assert second_len <= first_len
    assert any("Context window full" in line for line in result.status_log)


# --------------------------------------------------------------------------- #
# 5. After a tool call, the answer is grounded — LLM paraphrase is discarded
# --------------------------------------------------------------------------- #
def test_grounded_answer_overrides_llm_paraphrase(monkeypatch):
    # No auto-query template -> falls through to the LLM tool loop.
    monkeypatch.setattr(agent_mod, "try_auto_query", lambda q, f: {"success": False})

    aggregate_json = json.dumps({
        "collection": "Error_counts",
        "results": [
            {"_id": "Real Sensor Fault", "count": 7},
            {"_id": "Real Tray Jam", "count": 2},
        ],
    })
    monkeypatch.setattr(agent_mod, "execute_tool", lambda name, args, filters=None: aggregate_json)

    # Round 0: model calls aggregate. Round 1: model hallucinates a paraphrase.
    steps = [
        make_tool_step("aggregate", arguments='{"collection": "Error_counts"}'),
        make_text_step("There were 2 Controller Card Overheating events."),
    ]
    ollama = FakeOllama(steps)
    bot = PerformanceChatbot(ollama_client=ollama)

    result = bot.chat(
        "compare average error counts across clusters",
        use_rag=False,
        strict_grounded_answers=True,
        force_builtin_plots=True,
    )

    # Grounded values present, hallucination gone
    assert "Real Sensor Fault" in result.content
    assert "Real Tray Jam" in result.content
    assert "Controller Card Overheating" not in result.content
    assert result.model_used == "(grounded from MongoDB)"


# --------------------------------------------------------------------------- #
# 6. Data question where the model refuses to call tools -> honest fallback
# --------------------------------------------------------------------------- #
def test_no_tool_call_falls_back_to_auto_query(monkeypatch):
    calls = {"n": 0}

    def fake_auto_query(q, f):
        calls["n"] += 1
        # first call (pre-LLM gate) fails; later call also fails -> honest message
        return {"success": False}

    monkeypatch.setattr(agent_mod, "try_auto_query", fake_auto_query)

    steps = [make_text_step("I think it is probably fine.")]
    ollama = FakeOllama(steps)
    bot = PerformanceChatbot(ollama_client=ollama)

    result = bot.chat(
        "compare average error counts across clusters",
        use_rag=False,
        strict_grounded_answers=True,
    )
    assert "won't guess" in result.content.lower() or "couldn't run" in result.content.lower()
