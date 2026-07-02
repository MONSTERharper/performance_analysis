"""Minimal chatbot: ask a question, it queries MongoDB, it answers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from chatbot.knowledge_loader import build_system_prompt
from chatbot.mongo_tools import TOOL_DEFINITIONS, execute_tool
from chatbot.ollama_client import OllamaClient

MAX_TOOL_ROUNDS = 6
MAX_HISTORY_MESSAGES = 12  # keep the system prompt + recent turns


@dataclass
class Answer:
    content: str
    rows: list[dict] | None = None
    collection: str | None = None
    tools_used: list[str] = field(default_factory=list)


class Chatbot:
    def __init__(self, client: OllamaClient | None = None):
        self.client = client or OllamaClient()
        self.messages: list[dict[str, Any]] = []

    def reset(self) -> None:
        self.messages = []

    def _trim(self) -> list[dict]:
        """Send the system prompt plus the most recent turns."""
        if not self.messages:
            return []
        system = self.messages[0]
        rest = self.messages[1:]
        if len(rest) > MAX_HISTORY_MESSAGES:
            rest = rest[-MAX_HISTORY_MESSAGES:]
        return [system, *rest]

    def ask(self, question: str, on_status: Callable[[str], None] | None = None) -> Answer:
        self.client.warmup()
        if not self.messages:
            self.messages.append({"role": "system", "content": build_system_prompt()})
        self.messages.append({"role": "user", "content": question})

        tools_used: list[str] = []
        rows: list[dict] | None = None
        collection: str | None = None

        for _ in range(MAX_TOOL_ROUNDS):
            if on_status:
                on_status("Thinking…")
            resp = self.client.chat(self._trim(), tools=TOOL_DEFINITIONS, tool_choice="auto")
            msg = resp.choices[0].message

            entry: dict[str, Any] = {"role": "assistant"}
            if msg.content:
                entry["content"] = msg.content
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            self.messages.append(entry)

            if not msg.tool_calls:
                return Answer(
                    content=msg.content or "(no answer)",
                    rows=rows,
                    collection=collection,
                    tools_used=tools_used,
                )

            for tc in msg.tool_calls:
                name = tc.function.name
                tools_used.append(name)
                if on_status:
                    on_status(f"Querying MongoDB — {name}…")
                args = json.loads(tc.function.arguments or "{}")
                result = execute_tool(name, args)
                data = json.loads(result)
                if isinstance(data, dict):
                    if data.get("documents"):
                        rows, collection = data["documents"], data.get("collection")
                    elif data.get("results"):
                        rows, collection = data["results"], data.get("collection")
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        return Answer(
            content="I couldn't finish that after several query steps. Try rephrasing.",
            rows=rows,
            collection=collection,
            tools_used=tools_used,
        )
