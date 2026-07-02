"""Agent flow: tool-calling loop with a fake model and patched tools."""

from __future__ import annotations

import json

import chatbot.agent as agent_mod
from chatbot.agent import Chatbot
from conftest import FakeClient, text_step, tool_step


def test_direct_answer_without_tools(monkeypatch):
    monkeypatch.setattr(agent_mod, "build_system_prompt", lambda: "SYS")
    client = FakeClient([text_step("Hello!")])
    bot = Chatbot(client=client)
    ans = bot.ask("hi")
    assert ans.content == "Hello!"
    assert client.warmed  # warmup ran before inference
    assert ans.tools_used == []


def test_tool_call_then_answer(monkeypatch):
    monkeypatch.setattr(agent_mod, "build_system_prompt", lambda: "SYS")
    result_json = json.dumps({
        "collection": "Error_counts",
        "results": [{"error": "Sensor timeout", "count": 12}],
    })
    monkeypatch.setattr(agent_mod, "execute_tool", lambda name, args: result_json)

    steps = [
        tool_step("aggregate", arguments='{"collection": "Error_counts", "pipeline": []}'),
        text_step("The top error is Sensor timeout with 12 occurrences."),
    ]
    bot = Chatbot(client=FakeClient(steps))
    ans = bot.ask("what is the top error?")

    assert "Sensor timeout" in ans.content
    assert ans.tools_used == ["aggregate"]
    # rows captured from the aggregate result for display
    assert ans.rows == [{"error": "Sensor timeout", "count": 12}]
    assert ans.collection == "Error_counts"


def test_documents_captured_for_display(monkeypatch):
    monkeypatch.setattr(agent_mod, "build_system_prompt", lambda: "SYS")
    result_json = json.dumps({
        "collection": "sites",
        "documents": [{"site_key": "a"}, {"site_key": "b"}],
        "returned": 2,
    })
    monkeypatch.setattr(agent_mod, "execute_tool", lambda name, args: result_json)
    steps = [
        tool_step("find_documents", arguments='{"collection": "sites"}'),
        text_step("There are 2 sites."),
    ]
    bot = Chatbot(client=FakeClient(steps))
    ans = bot.ask("list sites")
    assert ans.rows == [{"site_key": "a"}, {"site_key": "b"}]
    assert ans.collection == "sites"


def test_reset_clears_history(monkeypatch):
    monkeypatch.setattr(agent_mod, "build_system_prompt", lambda: "SYS")
    bot = Chatbot(client=FakeClient([text_step("ok")]))
    bot.ask("hi")
    assert bot.messages
    bot.reset()
    assert bot.messages == []


def test_gives_up_after_max_rounds(monkeypatch):
    monkeypatch.setattr(agent_mod, "build_system_prompt", lambda: "SYS")
    monkeypatch.setattr(agent_mod, "execute_tool", lambda name, args: json.dumps({"results": []}))
    # Always calls a tool, never answers -> should bail out gracefully.
    steps = [tool_step("aggregate", arguments='{"collection":"x","pipeline":[]}')
             for _ in range(agent_mod.MAX_TOOL_ROUNDS)]
    bot = Chatbot(client=FakeClient(steps))
    ans = bot.ask("loop forever")
    assert "couldn't finish" in ans.content.lower()
