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


def _log(msg: str) -> None:
    """Print to the terminal so you can see the model working."""
    print(f"[chatbot] {msg}", flush=True)


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
        _log(f"warming up model '{self.client.model}'…")
        self.client.warmup()
        _log(f"USER: {question}")
        if not self.messages:
            self.messages.append({"role": "system", "content": build_system_prompt()})
        self.messages.append({"role": "user", "content": question})

        tools_used: list[str] = []
        rows: list[dict] | None = None
        collection: str | None = None

        for round_num in range(1, MAX_TOOL_ROUNDS + 1):
            if on_status:
                on_status("Thinking…")
            _log(f"round {round_num}: calling model…")
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
                _log(f"ANSWER: {(msg.content or '(no answer)')[:500]}")
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
                _log(f"TOOL CALL -> {name}({json.dumps(args, default=str)})")
                result = execute_tool(name, args)
                data = json.loads(result)
                if isinstance(data, dict):
                    if "error" in data:
                        _log(f"  result: ERROR {data['error']}")
                    elif data.get("documents") is not None:
                        rows, collection = data["documents"], data.get("collection")
                        _log(f"  result: {len(data['documents'])} document(s) from '{collection}'")
                    elif data.get("results") is not None:
                        rows, collection = data["results"], data.get("collection")
                        _log(f"  result: {len(data['results'])} row(s) from '{collection}'")
                    elif "count" in data:
                        _log(f"  result: count={data['count']}")
                    else:
                        _log(f"  result: {json.dumps(data, default=str)[:300]}")
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        _log("gave up after max tool rounds")
        return Answer(
            content="I couldn't finish that after several query steps. Try rephrasing.",
            rows=rows,
            collection=collection,
            tools_used=tools_used,
        )
