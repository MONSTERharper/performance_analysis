"""Shared fixtures and fakes for the chatbot test suite.

These tests never touch a real MongoDB or a real Ollama server.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --------------------------------------------------------------------------- #
# Fake OpenAI/Ollama response objects
# --------------------------------------------------------------------------- #
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


def make_text_step(content: str) -> FakeMessage:
    return FakeMessage(content=content)


def make_tool_step(name: str, arguments: str = "{}", call_id: str = "call_1") -> FakeMessage:
    return FakeMessage(content=None, tool_calls=[FakeToolCall(call_id, name, arguments)])


class ContextOverflowError(RuntimeError):
    """Mimics the Ollama 400 error string for context overflow."""

    def __init__(self) -> None:
        super().__init__(
            "request (8136 tokens) exceeds the available context size (4096 tokens), "
            "try increasing it"
        )


class FakeOllama:
    """Scriptable stand-in for OllamaCascadeClient.

    `steps` is a list where each item is one of:
      - a FakeMessage  -> returned as a normal completion
      - an Exception   -> raised on that call
    Calls are consumed in order. Every call's `messages` kwarg is recorded.
    """

    def __init__(self, steps: list, primary_model: str = "deepseek-r1:14b"):
        self.steps = list(steps)
        self.primary_model = primary_model
        self.fallback_model = "qwen2.5:14b"
        self.calls: list[dict] = []

    def warmup(self, *args, **kwargs):
        return [self.primary_model]

    def check_health(self):
        return {"ollama_reachable": True, "primary_available": True}

    def chat_completion(self, model_mode="auto", on_status=None, **kwargs):
        self.calls.append(kwargs)
        if not self.steps:
            raise AssertionError("FakeOllama ran out of scripted steps")
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return FakeResponse(step), self.primary_model, False


@pytest.fixture
def fake_ollama_factory():
    def _make(steps: list) -> FakeOllama:
        return FakeOllama(steps)
    return _make
