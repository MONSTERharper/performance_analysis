"""LLM agent with MongoDB tool use — powered by Ollama with model cascade."""

from __future__ import annotations

import json
from typing import Any

from chatbot.context_budget import (
    shrink_system_prompt,
    system_prompt_budget_tokens,
    trim_messages_for_llm,
)
from chatbot.events import ChatResult, StatusCallback, format_status
from chatbot.filters import QueryFilters
from chatbot.intent import (
    greeting_response,
    is_greeting_or_smalltalk,
    is_plot_request,
    requires_database_query,
    should_use_builtin_chart,
)
from chatbot.grounded_summary import (
    extract_raw_payload,
    format_grounded_answer,
    has_groundable_data,
)
from chatbot.knowledge_loader import build_system_prompt
from chatbot.plot_auto import try_auto_plot
from chatbot.query_auto import try_auto_query
from chatbot.mongo_tools import TOOL_DEFINITIONS, execute_tool
from chatbot.ollama_client import OLLAMA_NUM_CTX, ModelMode, OllamaCascadeClient

MAX_TOOL_ROUNDS = 8

TOOL_INSTRUCTIONS = """
## Tools (required for data)
- Call MongoDB tools for any numbers or records. Never invent values.
- Summaries must match tool JSON exactly.
- Raw tables: `fetch_raw_data`. Charts: only if built-in charts are disabled.
"""


DATA_TOOLS = frozenset({
    "list_collections",
    "describe_collection",
    "find_documents",
    "count_documents",
    "aggregate",
    "fetch_raw_data",
    "generate_plot",
    "auto_plot",
    "auto_query",
})


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

    def _result_from_auto_query(
        self,
        auto: dict,
        *,
        model_mode: ModelMode,
        rag_chunks: list[str],
        use_rag: bool,
        status_log: list[str],
        tool_calls_made: list[str],
    ) -> ChatResult:
        content = auto.get("summary", "Here are the results from MongoDB.")
        tool_calls_made.append("auto_query")
        return ChatResult(
            content=content,
            model_used="(auto query)",
            model_mode=model_mode,
            tool_calls_made=tool_calls_made,
            raw_data=auto.get("raw_data"),
            raw_data_meta=auto.get("raw_data_meta"),
            rag_chunks=rag_chunks,
            used_rag=use_rag,
            status_log=status_log,
        )

    def _try_auto_query_fallback(
        self,
        user_message: str,
        filters: QueryFilters | None,
        *,
        model_mode: ModelMode,
        rag_chunks: list[str],
        use_rag: bool,
        status_log: list[str],
        tool_calls_made: list[str],
        on_status: StatusCallback | None,
    ) -> ChatResult | None:
        self._emit(on_status, "querying_database", "auto", status_log)
        auto = try_auto_query(user_message, filters)
        if auto.get("success"):
            return self._result_from_auto_query(
                auto,
                model_mode=model_mode,
                rag_chunks=rag_chunks,
                use_rag=use_rag,
                status_log=status_log,
                tool_calls_made=tool_calls_made,
            )
        return None

    def _tools_for_request(self, force_builtin_plots: bool) -> list[dict]:
        if not force_builtin_plots:
            return TOOL_DEFINITIONS
        return [
            tool for tool in TOOL_DEFINITIONS
            if tool["function"]["name"] != "generate_plot"
        ]

    @staticmethod
    def _is_context_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            "context size" in text
            or "exceed_context" in text
            or "n_ctx" in text
            or "context length" in text
        )

    def _llm_messages(self, system_prompt: str, *, aggressive: bool) -> list[dict[str, Any]]:
        budget = system_prompt_budget_tokens(OLLAMA_NUM_CTX, aggressive=aggressive)
        prompt = shrink_system_prompt(system_prompt, max_tokens=budget)
        if aggressive:
            msgs = [m for m in self.messages if m.get("role") == "user"][-1:]
        else:
            msgs = trim_messages_for_llm(self.messages)
        return [{"role": "system", "content": prompt}, *msgs]

    def _chat_completion_with_context_retry(
        self,
        *,
        model_mode: ModelMode,
        system_prompt: str,
        tools: list[dict],
        tool_choice: str,
        on_status: StatusCallback | None,
        status_log: list[str],
    ):
        last_error: Exception | None = None
        for aggressive in (False, True):
            try:
                return self.ollama.chat_completion(
                    model_mode=model_mode,
                    on_status=lambda phase, detail: self._emit(on_status, phase, detail, status_log),
                    messages=self._llm_messages(system_prompt, aggressive=aggressive),
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=0.1,
                )
            except RuntimeError as exc:
                last_error = exc
                if aggressive or not self._is_context_error(exc):
                    raise
                status_log.append("Context window full — retrying with trimmed history and schema.")
        if last_error:
            raise last_error
        raise RuntimeError("LLM request failed")

    def _try_builtin_plot(
        self,
        user_message: str,
        filters: QueryFilters | None,
        *,
        auto_chart_with_data: bool,
        status_log: list[str],
        tool_calls_made: list[str],
        on_status: StatusCallback | None,
    ) -> dict | None:
        if not should_use_builtin_chart(user_message, auto_chart_with_data=auto_chart_with_data):
            return None
        self._emit(on_status, "generating_plot", "built-in", status_log)
        plot = try_auto_plot(user_message, filters)
        if plot.get("success"):
            tool_calls_made.append("auto_plot")
        return plot if plot.get("success") else None

    def chat(
        self,
        user_message: str,
        model_mode: ModelMode = "auto",
        on_status: StatusCallback | None = None,
        filters: QueryFilters | None = None,
        use_rag: bool = True,
        rag_top_k: int = 5,
        strict_grounded_answers: bool = True,
        force_builtin_plots: bool = True,
        auto_chart_with_data: bool = False,
    ) -> ChatResult:
        # Short-circuit greetings — no LLM call, no hallucinated queries
        if is_greeting_or_smalltalk(user_message):
            self.messages.append({"role": "user", "content": user_message})
            reply = greeting_response(filters)
            self.messages.append({"role": "assistant", "content": reply})
            return ChatResult(
                content=reply,
                model_used="(greeting handler)",
                model_mode=model_mode,
                rag_chunks=["(greeting — skipped)"],
                used_rag=False,
                status_log=["Greeting detected — responded without LLM/tools"],
            )

        # Built-in charts for explicit plot requests (reliable; Ollama plot tool often fails)
        if force_builtin_plots and is_plot_request(user_message):
            status_log: list[str] = []
            tool_calls_made: list[str] = []
            plot = self._try_builtin_plot(
                user_message,
                filters,
                auto_chart_with_data=auto_chart_with_data,
                status_log=status_log,
                tool_calls_made=tool_calls_made,
                on_status=on_status,
            )
            if plot:
                content = plot.get("summary", "Here is your chart.")
                self.messages.append({"role": "user", "content": user_message})
                self.messages.append({"role": "assistant", "content": content})
                self._emit(on_status, "complete", "", status_log)
                return ChatResult(
                    content=content,
                    model_used="(built-in chart)",
                    model_mode=model_mode,
                    tool_calls_made=tool_calls_made,
                    figure_json=plot.get("figure_json"),
                    rag_chunks=["(chart — RAG skipped)"],
                    used_rag=False,
                    status_log=status_log,
                )

        # Built-in queries for known patterns — skip LLM (saves context, avoids hallucination)
        if requires_database_query(user_message):
            status_log = []
            tool_calls_made = []
            auto_result = self._try_auto_query_fallback(
                user_message,
                filters,
                model_mode=model_mode,
                rag_chunks=[],
                use_rag=False,
                status_log=status_log,
                tool_calls_made=tool_calls_made,
                on_status=on_status,
            )
            if auto_result:
                figure_json = None
                if force_builtin_plots and should_use_builtin_chart(
                    user_message, auto_chart_with_data=auto_chart_with_data
                ):
                    plot = self._try_builtin_plot(
                        user_message,
                        filters,
                        auto_chart_with_data=auto_chart_with_data,
                        status_log=status_log,
                        tool_calls_made=tool_calls_made,
                        on_status=on_status,
                    )
                    if plot:
                        figure_json = plot.get("figure_json")
                        if plot.get("summary") and not is_plot_request(user_message):
                            auto_result.content = f"{auto_result.content}\n\n{plot['summary']}"
                self.messages.append({"role": "user", "content": user_message})
                self.messages.append({"role": "assistant", "content": auto_result.content})
                self._emit(on_status, "complete", auto_result.model_used, status_log)
                return ChatResult(
                    content=auto_result.content,
                    model_used=auto_result.model_used,
                    model_mode=model_mode,
                    tool_calls_made=auto_result.tool_calls_made,
                    figure_json=figure_json,
                    raw_data=auto_result.raw_data,
                    raw_data_meta=auto_result.raw_data_meta,
                    rag_chunks=auto_result.rag_chunks,
                    used_rag=auto_result.used_rag,
                    status_log=status_log,
                )

        # LLM plot tool path (only when built-in charts disabled)
        if is_plot_request(user_message) and not force_builtin_plots:
            self.messages.append({"role": "user", "content": user_message})
            status_log: list[str] = []
            self._emit(on_status, "generating_plot", "auto", status_log)
            plot = try_auto_plot(user_message, filters)
            if plot.get("success"):
                content = plot.get("summary", "Here is your chart.")
                self.messages.append({"role": "assistant", "content": content})
                self._emit(on_status, "complete", "", status_log)
                return ChatResult(
                    content=content,
                    model_used="(auto plot)",
                    model_mode=model_mode,
                    tool_calls_made=["auto_plot"],
                    figure_json=plot.get("figure_json"),
                    rag_chunks=["(plot — RAG skipped)"],
                    used_rag=False,
                    status_log=status_log,
                )

        self.messages.append({"role": "user", "content": user_message})
        tool_calls_made: list[str] = []
        status_log: list[str] = []
        tool_results: list[tuple[str, dict]] = []
        tools = self._tools_for_request(force_builtin_plots)

        # Ensure the model is loaded at the configured context window via the native
        # endpoint (the /v1 inference call cannot set num_ctx itself). No-op if already
        # warm. This makes CLI/API callers as safe as the Streamlit app.
        self.ollama.warmup(
            model_mode,
            on_status=lambda phase, detail: self._emit(on_status, phase, detail, status_log),
        )

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
        needs_db = requires_database_query(user_message)

        for round_num in range(MAX_TOOL_ROUNDS):
            self._emit(on_status, "thinking", "", status_log)

            tool_choice = (
                "required"
                if round_num == 0 and needs_db and not tool_calls_made
                else "auto"
            )
            try:
                response, model_used, used_fallback = self._chat_completion_with_context_retry(
                    model_mode=model_mode,
                    system_prompt=system_prompt,
                    tools=tools,
                    tool_choice=tool_choice,
                    on_status=on_status,
                    status_log=status_log,
                )
            except RuntimeError:
                if tool_choice == "required":
                    response, model_used, used_fallback = self._chat_completion_with_context_retry(
                        model_mode=model_mode,
                        system_prompt=system_prompt,
                        tools=tools,
                        tool_choice="auto",
                        on_status=on_status,
                        status_log=status_log,
                    )
                else:
                    raise
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
                content = msg.content or ""
                used_data_tools = any(name in DATA_TOOLS for name in tool_calls_made)

                if (
                    strict_grounded_answers
                    and used_data_tools
                    and has_groundable_data(tool_results)
                ):
                    grounded = format_grounded_answer(tool_results)
                    if grounded:
                        content = grounded
                        grounded_raw, grounded_meta = extract_raw_payload(tool_results)
                        if grounded_raw is not None:
                            raw_data = grounded_raw
                            raw_data_meta = grounded_meta
                        model_used = "(grounded from MongoDB)"

                if needs_db and not used_data_tools:
                    auto_result = self._try_auto_query_fallback(
                        user_message,
                        filters,
                        model_mode=model_mode,
                        rag_chunks=rag_chunks,
                        use_rag=use_rag,
                        status_log=status_log,
                        tool_calls_made=tool_calls_made,
                        on_status=on_status,
                    )
                    if auto_result:
                        self.messages.append({"role": "assistant", "content": auto_result.content})
                        self._emit(on_status, "complete", auto_result.model_used, status_log)
                        return auto_result

                    content = (
                        "I couldn't run a database query for that question, so I won't guess the answer. "
                        "Try rephrasing with a specific metric (e.g. *top errors*, *slides by site*, "
                        "*list sites*), or check that Ollama tool-calling is enabled."
                    )

                if force_builtin_plots:
                    plot = self._try_builtin_plot(
                        user_message,
                        filters,
                        auto_chart_with_data=auto_chart_with_data,
                        status_log=status_log,
                        tool_calls_made=tool_calls_made,
                        on_status=on_status,
                    )
                    if plot:
                        figure_json = plot.get("figure_json")
                        if plot.get("summary"):
                            if is_plot_request(user_message) or not content:
                                content = plot["summary"]
                            elif "built-in chart" not in content.lower():
                                content = f"{content}\n\n{plot['summary']}"
                elif is_plot_request(user_message) and not figure_json:
                    self._emit(on_status, "generating_plot", "auto", status_log)
                    plot = try_auto_plot(user_message, filters)
                    if plot.get("success"):
                        figure_json = plot.get("figure_json")
                        tool_calls_made.append("auto_plot")
                        if plot.get("summary"):
                            content = plot["summary"] if not content else f"{plot['summary']}\n\n{content}"

                self._emit(on_status, "complete", model_used, status_log)
                return ChatResult(
                    content=content,
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
                if name != "generate_plot":
                    tool_results.append((name, result_data))

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

        if needs_db and not any(name in DATA_TOOLS for name in tool_calls_made):
            auto_result = self._try_auto_query_fallback(
                user_message,
                filters,
                model_mode=model_mode,
                rag_chunks=rag_chunks,
                use_rag=use_rag,
                status_log=status_log,
                tool_calls_made=tool_calls_made,
                on_status=on_status,
            )
            if auto_result:
                return auto_result

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
