"""LLM agent with MongoDB tool use — powered by Ollama with model cascade."""

from __future__ import annotations

import json
from typing import Any

from chatbot.events import ChatResult, StatusCallback, format_status
from chatbot.filters import QueryFilters
from chatbot.knowledge_loader import build_system_prompt
from chatbot.mongo_tools import TOOL_DEFINITIONS, execute_tool
from chatbot.ollama_client import ModelMode, OllamaCascadeClient

MAX_TOOL_ROUNDS = 8

TOOL_INSTRUCTIONS = """
## Plotting & Visualizations
When the user asks for charts, plots, graphs, or trends:
1. Use the `generate_plot` tool with Python code
2. Query MongoDB via `get_database()` (returns test_db2)
3. Use pandas (`pd`) and plotly (`px` or `go`)
4. Always assign the final chart to variable `fig`
5. After the plot is generated, briefly explain what the chart shows

## Raw Data / Tables
When the user asks for raw data, a table, records, spreadsheet, export, or "show me the data":
1. Use the `fetch_raw_data` tool (NOT find_documents)
2. Choose the right collection and fields
3. Apply active sidebar filters via the tool (they are merged automatically)
4. Summarize row count and mention if data was truncated

Example collections:
- slide_count_values: daily slide counts (`date_str`, `Specified cycle slides scanned`)
- scanner_stoppages: downtime (`date_str`, `site`, `diff`, `error`)
- load_time_analysis: load durations (`duration_seconds`, `date_str`, `site`)
- regression_metrics: scan time vs area (`average_scan_time`, `date_str`, `site`)
- Error_counts: error frequency (`error`, `count`, `date_str`)
- raw_error_logs: individual errors (`errorCode`, `errorRootCause`, `date_str`)
"""


class PerformanceChatbot:
    def __init__(self, ollama_client: OllamaCascadeClient | None = None):
        self.ollama = ollama_client or OllamaCascadeClient()
        self.messages: list[dict[str, Any]] = []
        self.last_model_used: str = ""

    def reset(self) -> None:
        self.messages = []
        self.last_model_used = ""

    def _build_system_prompt(
        self,
        user_message: str,
        filters: QueryFilters | None,
        use_rag: bool,
        rag_top_k: int,
    ) -> tuple[str, list[str]]:
        prompt, rag_chunks = build_system_prompt(
            query=user_message,
            use_rag=use_rag,
            top_k=rag_top_k,
        )
        prompt += TOOL_INSTRUCTIONS
        if filters and filters.to_prompt_context():
            prompt += "\n\n" + filters.to_prompt_context()
        return prompt, rag_chunks

    def _emit(self, callback: StatusCallback | None, phase: str, detail: str, log: list[str]) -> None:
        log.append(format_status(phase, detail))
        if callback:
            callback(phase, detail)

    def chat(
        self,
        user_message: str,
        model_mode: ModelMode = "auto",
        on_status: StatusCallback | None = None,
        filters: QueryFilters | None = None,
        use_rag: bool = True,
        rag_top_k: int = 5,
    ) -> ChatResult:
        self.messages.append({"role": "user", "content": user_message})
        tool_calls_made: list[str] = []
        status_log: list[str] = []

        self._emit(on_status, "retrieving_context", "", status_log)
        system_prompt, rag_chunks = self._build_system_prompt(
            user_message, filters, use_rag, rag_top_k
        )
        if use_rag:
            status_log.append(f"RAG: {len(rag_chunks)} chunks — {', '.join(rag_chunks[:4])}{'...' if len(rag_chunks) > 4 else ''}")

        model_used = self.ollama.primary_model
        used_fallback = False
        figure_json: str | None = None
        raw_data: list[dict] | None = None
        raw_data_meta: dict | None = None

        for _ in range(MAX_TOOL_ROUNDS):
            self._emit(on_status, "thinking", "", status_log)

            response, model_used, used_fallback = self.ollama.chat_completion(
                model_mode=model_mode,
                on_status=lambda phase, detail: self._emit(on_status, phase, detail, status_log),
                messages=[{"role": "system", "content": system_prompt}, *self.messages],
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.2,
            )
            self.last_model_used = model_used
            msg = response.choices[0].message

            assistant_entry: dict[str, Any] = {"role": "assistant"}
            if msg.content:
                assistant_entry["content"] = msg.content
            if msg.tool_calls:
                assistant_entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            self.messages.append(assistant_entry)

            if not msg.tool_calls:
                self._emit(on_status, "complete", model_used, status_log)
                return ChatResult(
                    content=msg.content or "",
                    model_used=model_used,
                    model_mode=model_mode,
                    tool_calls_made=tool_calls_made,
                    figure_json=figure_json,
                    raw_data=raw_data,
                    raw_data_meta=raw_data_meta,
                    rag_chunks=rag_chunks,
                    used_rag=use_rag,
                    status_log=status_log,
                    used_fallback=used_fallback,
                )

            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                tool_calls_made.append(name)
                args = json.loads(tool_call.function.arguments or "{}")

                if name == "generate_plot":
                    self._emit(on_status, "generating_plot", "", status_log)
                elif name == "fetch_raw_data":
                    self._emit(on_status, "fetching_data", args.get("collection", ""), status_log)
                else:
                    self._emit(on_status, "querying_database", name, status_log)

                result_str = execute_tool(name, args, filters=filters)
                result_data = json.loads(result_str)

                if name == "generate_plot" and result_data.get("success") and result_data.get("figure_json"):
                    figure_json = result_data["figure_json"]

                if name == "fetch_raw_data" and result_data.get("success"):
                    raw_data = result_data.get("documents", [])
                    raw_data_meta = {
                        "collection": result_data.get("collection"),
                        "returned": result_data.get("returned"),
                        "total_matching": result_data.get("total_matching"),
                        "truncated": result_data.get("truncated"),
                        "filter": result_data.get("filter"),
                    }

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                })

        self._emit(on_status, "complete", model_used, status_log)
        return ChatResult(
            content="I reached the maximum number of query steps. Please try a more specific question.",
            model_used=model_used,
            model_mode=model_mode,
            tool_calls_made=tool_calls_made,
            figure_json=figure_json,
            raw_data=raw_data,
            raw_data_meta=raw_data_meta,
            rag_chunks=rag_chunks,
            used_rag=use_rag,
            status_log=status_log,
            used_fallback=used_fallback,
        )
