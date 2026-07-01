"""Streamlit web UI for the performance analytics chatbot."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.io as pio
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from chatbot.agent import PerformanceChatbot
from chatbot.events import format_status
from chatbot.export_utils import (
    content_to_txt,
    figure_to_html,
    figure_to_png_bytes,
    records_to_csv,
    records_to_json,
)
from chatbot.filters import QueryFilters, default_date_range, load_sites
from chatbot.ollama_client import OllamaCascadeClient
from chatbot.saved_queries import delete_query, load_queries, save_query

st.set_page_config(
    page_title="Scanner Performance Chat",
    page_icon="🔬",
    layout="wide",
)

EXAMPLE_QUESTIONS = [
    "Plot total slides scanned day-wise for the last 5 weeks",
    "Give me the raw error logs for the selected site and date range",
    "What are the top 10 error codes across all sites?",
    "Show raw scanner stoppages data as a table",
    "Plot average load duration by site as a bar chart",
    "Show regression scan time trend for the filtered period",
]

MODEL_MODE_OPTIONS = {
    "Auto (DeepSeek → Qwen fallback)": "auto",
    "DeepSeek only": "deepseek",
    "Qwen only": "qwen",
}


def init_session_state() -> None:
    start, end = default_date_range(5)
    defaults = {
        "messages": [],
        "bot": PerformanceChatbot(),
        "ollama": OllamaCascadeClient(),
        "model_mode": "auto",
        "model_mode_label": "Auto (DeepSeek → Qwen fallback)",
        "filter_site_key": None,
        "filter_site_name": None,
        "filter_date_start": start,
        "filter_date_end": end,
        "filter_apply_site": False,
        "filter_apply_dates": True,
        "last_user_query": "",
        "use_rag": True,
        "rag_top_k": 5,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def build_filters() -> QueryFilters:
    return QueryFilters(
        site_key=st.session_state.filter_site_key,
        site_name=st.session_state.filter_site_name,
        date_start=st.session_state.filter_date_start,
        date_end=st.session_state.filter_date_end,
        apply_site=st.session_state.filter_apply_site,
        apply_dates=st.session_state.filter_apply_dates,
    )


def render_plot(figure_json: str | None) -> None:
    if not figure_json:
        return
    try:
        fig = pio.from_json(figure_json)
        st.plotly_chart(fig, use_container_width=True)
    except Exception as exc:
        st.warning(f"Could not render chart: {exc}")


def render_raw_data(raw_data: list[dict] | None, meta: dict | None) -> None:
    if not raw_data:
        return
    df = pd.DataFrame(raw_data)
    if meta:
        returned = meta.get("returned", len(raw_data))
        total = meta.get("total_matching", returned)
        coll = meta.get("collection", "data")
        note = f"**{returned:,}** rows from `{coll}`"
        if meta.get("truncated"):
            note += f" (of {total:,} matching — truncated)"
        st.caption(note)
    st.dataframe(df, use_container_width=True, height=min(400, 35 * len(df) + 38))


def render_export_buttons(msg: dict, key_prefix: str) -> None:
    cols = st.columns(5)
    idx = 0

    if msg.get("raw_data"):
        records = msg["raw_data"]
        cols[idx].download_button(
            "CSV",
            data=records_to_csv(records),
            file_name=f"{msg.get('raw_data_meta', {}).get('collection', 'data')}.csv",
            mime="text/csv",
            key=f"{key_prefix}_csv",
            use_container_width=True,
        )
        idx += 1
        cols[idx].download_button(
            "JSON",
            data=records_to_json(records),
            file_name=f"{msg.get('raw_data_meta', {}).get('collection', 'data')}.json",
            mime="application/json",
            key=f"{key_prefix}_json",
            use_container_width=True,
        )
        idx += 1

    if msg.get("figure_json"):
        cols[idx].download_button(
            "Chart HTML",
            data=figure_to_html(msg["figure_json"]),
            file_name="chart.html",
            mime="text/html",
            key=f"{key_prefix}_html",
            use_container_width=True,
        )
        idx += 1
        png = figure_to_png_bytes(msg["figure_json"])
        if png:
            cols[idx].download_button(
                "Chart PNG",
                data=png,
                file_name="chart.png",
                mime="image/png",
                key=f"{key_prefix}_png",
                use_container_width=True,
            )
            idx += 1

    if msg.get("content"):
        cols[idx].download_button(
            "Response TXT",
            data=content_to_txt(msg["content"]),
            file_name="response.txt",
            mime="text/plain",
            key=f"{key_prefix}_txt",
            use_container_width=True,
        )


def render_message(msg: dict, index: int) -> None:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        render_plot(msg.get("figure_json"))
        render_raw_data(msg.get("raw_data"), msg.get("raw_data_meta"))

        if msg["role"] == "assistant":
            render_export_buttons(msg, f"export_{index}")

        meta_parts = []
        if msg.get("model"):
            meta_parts.append(f"Model: `{msg['model']}`")
        if msg.get("model_mode"):
            meta_parts.append(f"Mode: `{msg['model_mode']}`")
        if msg.get("used_fallback"):
            meta_parts.append("Used fallback model")
        if msg.get("tools"):
            meta_parts.append(f"Tools: {', '.join(msg['tools'])}")
        if msg.get("used_rag"):
            meta_parts.append(f"RAG: {len(msg.get('rag_chunks', []))} chunks")
        if meta_parts:
            st.caption(" · ".join(meta_parts))

        if msg.get("rag_chunks") and msg["role"] == "assistant":
            with st.expander("RAG context used"):
                for title in msg["rag_chunks"]:
                    st.text(f"• {title}")

        if msg.get("status_log") and msg["role"] == "assistant":
            with st.expander("Activity log"):
                for line in msg["status_log"]:
                    st.text(line)


def render_rag_settings() -> tuple[bool, int]:
    st.subheader("Knowledge (RAG)")
    use_rag = st.toggle(
        "Use RAG (recommended)",
        value=st.session_state.use_rag,
        help="Retrieve only relevant schema sections per query instead of the full 26k doc.",
    )
    top_k = st.slider(
        "Chunks to retrieve",
        min_value=3,
        max_value=10,
        value=st.session_state.rag_top_k,
        disabled=not use_rag,
        help="More chunks = more context but larger prompt.",
    )
    st.session_state.use_rag = use_rag
    st.session_state.rag_top_k = top_k
    if use_rag:
        st.caption("Sends ~3 core + top matching sections per query")
    else:
        st.caption("Sends full knowledge base every query")
    return use_rag, top_k


def render_filter_sidebar() -> QueryFilters:
    sites = load_sites()
    site_options = ["All sites"] + [s["site_name"] for s in sites]
    site_key_map = {s["site_name"]: s["site_key"] for s in sites}

    st.subheader("Filters")

    apply_site = st.checkbox("Filter by site", value=st.session_state.filter_apply_site)
    default_site_index = 0
    if st.session_state.filter_site_name and st.session_state.filter_site_name in site_options:
        default_site_index = site_options.index(st.session_state.filter_site_name)
    selected_site = st.selectbox(
        "Site",
        options=site_options,
        index=default_site_index,
        disabled=not apply_site,
    )
    st.session_state.filter_apply_site = apply_site
    if apply_site and selected_site != "All sites":
        st.session_state.filter_site_name = selected_site
        st.session_state.filter_site_key = site_key_map.get(selected_site)
    else:
        st.session_state.filter_site_name = None
        st.session_state.filter_site_key = None

    apply_dates = st.checkbox("Filter by date range", value=st.session_state.filter_apply_dates)
    start, end = default_date_range(5)
    col1, col2 = st.columns(2)
    with col1:
        date_start = st.date_input(
            "From",
            value=st.session_state.filter_date_start or start,
            disabled=not apply_dates,
        )
    with col2:
        date_end = st.date_input(
            "To",
            value=st.session_state.filter_date_end or end,
            disabled=not apply_dates,
        )
    st.session_state.filter_apply_dates = apply_dates
    if apply_dates:
        st.session_state.filter_date_start = date_start
        st.session_state.filter_date_end = date_end

    filters = build_filters()
    if filters.is_active():
        st.info(f"Active: {filters.summary()}")
    return filters


def render_saved_queries() -> None:
    st.subheader("Saved queries")
    queries = load_queries()

    save_col1, save_col2 = st.columns([3, 1])
    with save_col1:
        st.caption("Save your last question with current filters")
    with save_col2:
        if st.button("Save", use_container_width=True, disabled=not st.session_state.last_user_query):
            entry = save_query(
                st.session_state.last_user_query,
                site_key=st.session_state.filter_site_key,
                site_name=st.session_state.filter_site_name,
                date_start=str(st.session_state.filter_date_start) if st.session_state.filter_apply_dates else None,
                date_end=str(st.session_state.filter_date_end) if st.session_state.filter_apply_dates else None,
            )
            st.toast(f"Saved: {entry['query'][:40]}...")
            st.rerun()

    if not queries:
        st.caption("No saved queries yet.")
        return

    for q in queries[:10]:
        label = q["query"][:50] + ("..." if len(q["query"]) > 50 else "")
        c1, c2 = st.columns([4, 1])
        with c1:
            if st.button(label, key=f"sq_{q['id']}", use_container_width=True):
                st.session_state.pending_question = q["query"]
                if q.get("site_key"):
                    st.session_state.filter_apply_site = True
                    st.session_state.filter_site_key = q["site_key"]
                    st.session_state.filter_site_name = q.get("site_name")
                if q.get("date_start"):
                    st.session_state.filter_apply_dates = True
                    st.session_state.filter_date_start = date.fromisoformat(q["date_start"])
                if q.get("date_end"):
                    st.session_state.filter_date_end = date.fromisoformat(q["date_end"])
                st.rerun()
        with c2:
            if st.button("✕", key=f"del_{q['id']}"):
                delete_query(q["id"])
                st.rerun()


def render_sidebar() -> tuple[str, QueryFilters]:
    ollama: OllamaCascadeClient = st.session_state.ollama

    with st.sidebar:
        st.header("Settings")

        model_label = st.radio(
            "Model selection",
            options=list(MODEL_MODE_OPTIONS.keys()),
            index=list(MODEL_MODE_OPTIONS.values()).index(st.session_state.model_mode),
            help="Auto uses DeepSeek first, falls back to Qwen on failure.",
        )
        st.session_state.model_mode = MODEL_MODE_OPTIONS[model_label]
        st.session_state.model_mode_label = model_label

        st.caption(f"DeepSeek: `{ollama.primary_model}`")
        st.caption(f"Qwen: `{ollama.fallback_model}`")

        if st.button("Check Ollama & Models", use_container_width=True):
            health = ollama.check_health()
            if health["ollama_reachable"]:
                st.success("Ollama is running")
            else:
                st.error("Cannot reach Ollama. Run: `ollama serve`")
            for label, key in [("DeepSeek", "primary_available"), ("Qwen", "fallback_available")]:
                model = health["primary_model"] if key == "primary_available" else health["fallback_model"]
                if health[key]:
                    st.success(f"{label} `{model}` ready")
                else:
                    st.warning(f"Pull: `ollama pull {model}`")

        st.divider()
        rag_settings = render_rag_settings()

        st.divider()
        filters = render_filter_sidebar()

        st.divider()
        render_saved_queries()

        st.divider()
        st.markdown("**Database:** `test_db2`")
        if st.button("Clear conversation", use_container_width=True):
            st.session_state.messages = []
            st.session_state.bot.reset()
            st.rerun()

        st.divider()
        st.markdown("**Example questions**")
        for q in EXAMPLE_QUESTIONS:
            if st.button(q, key=f"ex_{hash(q)}", use_container_width=True):
                st.session_state.pending_question = q

    return st.session_state.model_mode, filters, rag_settings[0], rag_settings[1]


def _result_to_message(result, user_query: str) -> dict:
    return {
        "role": "assistant",
        "content": result.content,
        "model": result.model_used,
        "model_mode": result.model_mode,
        "used_fallback": result.used_fallback,
        "tools": result.tool_calls_made,
        "figure_json": result.figure_json,
        "raw_data": result.raw_data,
        "raw_data_meta": result.raw_data_meta,
        "rag_chunks": result.rag_chunks,
        "used_rag": result.used_rag,
        "status_log": result.status_log,
        "user_query": user_query,
    }


def run_chat_turn(
    user_input: str,
    model_mode: str,
    filters: QueryFilters,
    use_rag: bool,
    rag_top_k: int,
) -> None:
    st.session_state.last_user_query = user_input
    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.markdown(user_input)
        if filters.is_active():
            st.caption(f"Filters: {filters.summary()}")

    with st.chat_message("assistant"):
        status_lines: list[str] = []
        status_placeholder = st.empty()
        content_placeholder = st.empty()
        plot_placeholder = st.container()
        data_placeholder = st.container()
        export_placeholder = st.container()

        def on_status(phase: str, detail: str) -> None:
            label = format_status(phase, detail)
            status_lines.append(label)
            status_placeholder.info(label)

        try:
            result = st.session_state.bot.chat(
                user_input,
                model_mode=model_mode,
                on_status=on_status,
                filters=filters,
                use_rag=use_rag,
                rag_top_k=rag_top_k,
            )

            status_placeholder.empty()
            content_placeholder.markdown(result.content)

            if result.figure_json:
                with plot_placeholder:
                    render_plot(result.figure_json)

            if result.raw_data:
                with data_placeholder:
                    render_raw_data(result.raw_data, result.raw_data_meta)

            meta = []
            if result.model_used:
                meta.append(f"Model: `{result.model_used}`")
            meta.append(f"Mode: `{result.model_mode}`")
            if result.used_fallback:
                meta.append("Used fallback")
            if result.used_rag:
                meta.append(f"RAG: {len(result.rag_chunks)} chunks")
            if result.tool_calls_made:
                meta.append(f"Tools: {', '.join(result.tool_calls_made)}")
            st.caption(" · ".join(meta))

            if result.rag_chunks:
                with st.expander("RAG context used"):
                    for title in result.rag_chunks:
                        st.text(f"• {title}")

            msg = _result_to_message(result, user_input)
            with export_placeholder:
                render_export_buttons(msg, f"live_{len(st.session_state.messages)}")

            with st.expander("Activity log"):
                for line in result.status_log:
                    st.text(line)

            st.session_state.messages.append(msg)
        except Exception as exc:
            status_placeholder.error(format_status("error", str(exc)))
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"**Error:** {exc}",
                "status_log": status_lines,
            })


def render_chat(model_mode: str, filters: QueryFilters, use_rag: bool, rag_top_k: int) -> None:
    for i, msg in enumerate(st.session_state.messages):
        render_message(msg, i)

    pending = st.session_state.pop("pending_question", None)
    user_input = pending or st.chat_input(
        "Ask questions, request plots, raw data tables, or exports..."
    )

    if user_input:
        run_chat_turn(user_input, model_mode, filters, use_rag, rag_top_k)


def main() -> None:
    init_session_state()
    st.title("Scanner Performance Analytics")
    filters = build_filters()
    rag_label = "RAG on" if st.session_state.use_rag else "full KB"
    filter_note = f" · Filters: **{filters.summary()}**" if filters.is_active() else ""
    st.caption(
        f"Explore `test_db2` — ask questions, plot charts, or export raw data. "
        f"Model: **{st.session_state.model_mode_label}** · Knowledge: **{rag_label}**{filter_note}"
    )
    model_mode, filters, use_rag, rag_top_k = render_sidebar()
    render_chat(model_mode, filters, use_rag, rag_top_k)


if __name__ == "__main__":
    main()
