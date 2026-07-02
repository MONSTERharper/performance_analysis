"""Shared fakes for the chatbot test suite (no live MongoDB / Ollama)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str):
        self.id = call_id
        self.type = "function"
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content: str | None = None, tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or None


class FakeChoice:
    def __init__(self, message: FakeMessage):
        self.message = message


class FakeResponse:
    def __init__(self, message: FakeMessage):
        self.choices = [FakeChoice(message)]


def text_step(content: str) -> FakeMessage:
    return FakeMessage(content=content)


def tool_step(name: str, arguments: str = "{}", call_id: str = "call_1") -> FakeMessage:
    return FakeMessage(content=None, tool_calls=[FakeToolCall(call_id, name, arguments)])


class FakeClient:
    """Scriptable stand-in for OllamaClient. `steps` are returned in order."""

    def __init__(self, steps: list, model: str = "qwen2.5:14b"):
        self.steps = list(steps)
        self.model = model
        self.calls: list[dict] = []
        self.warmed = False

    def warmup(self) -> None:
        self.warmed = True

    def chat(self, messages, tools=None, tool_choice="auto"):
        self.calls.append({"messages": messages, "tools": tools})
        if not self.steps:
            raise AssertionError("FakeClient ran out of scripted steps")
        return FakeResponse(self.steps.pop(0))
