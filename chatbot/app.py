"""Streamlit web UI — clean chat interface with Settings page."""

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
    page_title="Performance AI",
    page_icon="🔬",
    layout="centered",
    initial_sidebar_state="collapsed",
)

MODEL_MODE_OPTIONS = {
    "Auto (DeepSeek → Qwen)": "auto",
    "DeepSeek only": "deepseek",
    "Qwen only": "qwen",
}

STARTER_PROMPTS = [
    ("📈 Slides trend", "Plot total slides scanned day-wise for the last 5 weeks"),
    ("⏱️ Load times", "Plot average load duration by site"),
    ("⚠️ Top errors", "What are the top 10 error codes?"),
    ("📋 Raw data", "Show raw scanner stoppages as a table"),
]

CSS = """
<style>
    #MainMenu, footer, header {visibility: hidden; height: 0;}
    .block-container {padding-top: 0.5rem; padding-bottom: 4rem; max-width: 46rem;}
    .app-header {
        position: sticky; top: 0; z-index: 999;
        background: var(--background-color);
        border-bottom: 1px solid rgba(128,128,128,0.2);
        padding: 0.75rem 0 0.75rem 0; margin-bottom: 1rem;
    }
    .app-title {font-size: 1.15rem; font-weight: 600; margin: 0; line-height: 1.3;}
    .app-sub {font-size: 0.8rem; opacity: 0.55; margin: 0;}
    .status-pill {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 6px 14px; border-radius: 20px;
        background: rgba(99,102,241,0.12); color: #6366f1;
        font-size: 0.82rem; font-weight: 500; margin: 0.25rem 0 0.75rem 0;
    }
    .welcome-box {
        text-align: center; padding: 2.5rem 1rem 1.5rem 1rem;
    }
    .welcome-box h2 {font-size: 1.6rem; font-weight: 600; margin-bottom: 0.25rem;}
    .welcome-box p {opacity: 0.6; font-size: 0.95rem; margin-bottom: 1.5rem;}
    .chip-row {display: flex; flex-wrap: wrap; gap: 0.5rem; justify-content: center;}
    div[data-testid="stChatMessage"] {
        background: transparent !important;
        border: none !important;
        padding: 0.25rem 0 !important;
    }
    .export-row {margin-top: 0.5rem;}
    .settings-back {margin-bottom: 1rem;}
</style>
"""


def init_session_state() -> None:
    start, end = default_date_range(5)

    # One-time: old sessions had date filter on by default
    if "_filters_migrated" not in st.session_state and "filter_apply_dates" in st.session_state:
        st.session_state.filter_apply_dates = False
        st.session_state.filter_apply_site = False
    if "_filters_migrated" not in st.session_state:
        st.session_state._filters_migrated = True

    defaults = {
        "messages": [],
        "bot": PerformanceChatbot(),
        "ollama": OllamaCascadeClient(),
        "model_mode": "auto",
        "model_mode_label": "Auto (DeepSeek → Qwen)",
        "filter_site_key": None,
        "filter_site_name": None,
        "filter_date_start": start,
        "filter_date_end": end,
        "filter_apply_site": False,
        "filter_apply_dates": False,
        "last_user_query": "",
        "use_rag": True,
        "rag_top_k": 5,
        "strict_grounded_answers": True,
        "force_builtin_plots": True,
        "auto_chart_with_data": False,
        "models_warmed": False,
        "nav": "Chat",
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


def render_header() -> None:
    c1, c2, c3 = st.columns([5, 1, 1])
    with c1:
        st.markdown(
            '<p class="app-title">Performance AI</p>'
            '<p class="app-sub">Scanner analytics · test_db2</p>',
            unsafe_allow_html=True,
        )
    with c2:
        if st.button("＋ New", help="Clear chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.bot.reset()
            st.rerun()
    with c3:
        if st.button("⚙️", help="Settings", use_container_width=True):
            st.session_state.nav = "Settings"
            st.rerun()


def render_plot(figure_json: str | None, key: str) -> None:
    if not figure_json:
        return
    try:
        fig = pio.from_json(figure_json)
        st.plotly_chart(fig, use_container_width=True, key=key)
    except Exception as exc:
        st.error(f"Chart error: {exc}")


def render_raw_data(raw_data: list[dict] | None, meta: dict | None) -> None:
    if not raw_data:
        return
    df = pd.DataFrame(raw_data)
    label = f"{len(df):,} rows"
    if meta and meta.get("collection"):
        label = f"`{meta['collection']}` · {meta.get('returned', len(df)):,} rows"
        if meta.get("truncated"):
            label += " (truncated)"
    st.caption(label)
    st.dataframe(df, use_container_width=True, height=min(320, 35 * len(df) + 38))


def render_exports(msg: dict, key: str) -> None:
    with st.container():
        cols = st.columns(6)
        i = 0
        if msg.get("raw_data"):
            cols[i].download_button("⬇ CSV", records_to_csv(msg["raw_data"]),
                                    file_name="data.csv", mime="text/csv", key=f"{key}_csv")
            i += 1
            cols[i].download_button("⬇ JSON", records_to_json(msg["raw_data"]),
                                    file_name="data.json", mime="application/json", key=f"{key}_json")
            i += 1
        if msg.get("figure_json"):
            cols[i].download_button("⬇ HTML", figure_to_html(msg["figure_json"]),
                                    file_name="chart.html", mime="text/html", key=f"{key}_html")
            i += 1
            png = figure_to_png_bytes(msg["figure_json"])
            if png:
                cols[i].download_button("⬇ PNG", png, file_name="chart.png",
                                        mime="image/png", key=f"{key}_png")
                i += 1
        if msg.get("content"):
            cols[i].download_button("⬇ TXT", content_to_txt(msg["content"]),
                                    file_name="response.txt", mime="text/plain", key=f"{key}_txt")


def render_message(msg: dict, index: int) -> None:
    with st.chat_message(msg["role"], avatar="🧑‍💻" if msg["role"] == "user" else "🔬"):
        if msg["role"] == "assistant":
            render_plot(msg.get("figure_json"), key=f"hist_plot_{index}")
            render_raw_data(msg.get("raw_data"), msg.get("raw_data_meta"))
            if msg.get("content"):
                st.markdown(msg["content"])
            if msg.get("figure_json") or msg.get("raw_data"):
                render_exports(msg, f"hist_{index}")
            if msg.get("model") or msg.get("tools"):
                with st.expander("Details"):
                    if msg.get("model"):
                        st.caption(f"Model: {msg['model']}")
                    if msg.get("tools"):
                        st.caption(f"Tools: {', '.join(msg['tools'])}")
        else:
            st.markdown(msg["content"])


def render_welcome() -> None:
    st.markdown(
        """
        <div class="welcome-box">
            <h2>What would you like to analyze?</h2>
            <p>Ask about scanner performance, request charts, or export raw data.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(2)
    for i, (label, query) in enumerate(STARTER_PROMPTS):
        if cols[i % 2].button(label, key=f"chip_{i}", use_container_width=True):
            st.session_state.pending_question = query
            st.rerun()


def warmup_models() -> None:
    if st.session_state.models_warmed:
        return
    ollama: OllamaCascadeClient = st.session_state.ollama
    with st.spinner("Preparing models (first time only)…"):
        ollama.warmup(st.session_state.model_mode)
    st.session_state.models_warmed = True


def run_chat_turn(user_input: str) -> None:
    filters = build_filters()
    st.session_state.last_user_query = user_input

    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(user_input)

    with st.chat_message("assistant", avatar="🔬"):
        status = st.empty()

        def on_status(phase: str, detail: str) -> None:
            if phase == "warming_model":
                st.session_state.models_warmed = False
            status.markdown(
                f'<div class="status-pill">{format_status(phase, detail)}</div>',
                unsafe_allow_html=True,
            )

        try:
            result = st.session_state.bot.chat(
                user_input,
                model_mode=st.session_state.model_mode,
                on_status=on_status,
                filters=filters,
                use_rag=st.session_state.use_rag,
                rag_top_k=st.session_state.rag_top_k,
                strict_grounded_answers=st.session_state.strict_grounded_answers,
                force_builtin_plots=st.session_state.force_builtin_plots,
                auto_chart_with_data=st.session_state.auto_chart_with_data,
            )
            status.empty()

            render_plot(result.figure_json, key=f"live_plot_{len(st.session_state.messages)}")
            render_raw_data(result.raw_data, result.raw_data_meta)
            if result.content:
                st.markdown(result.content)

            msg = {
                "role": "assistant",
                "content": result.content,
                "model": result.model_used,
                "tools": result.tool_calls_made,
                "figure_json": result.figure_json,
                "raw_data": result.raw_data,
                "raw_data_meta": result.raw_data_meta,
            }
            if result.figure_json or result.raw_data:
                render_exports(msg, f"live_{len(st.session_state.messages)}")
            st.session_state.messages.append({"role": "user", "content": user_input})
            st.session_state.messages.append(msg)
        except Exception as exc:
            status.empty()
            st.error(str(exc))
            st.session_state.messages.append({"role": "user", "content": user_input})
            st.session_state.messages.append({"role": "assistant", "content": f"**Error:** {exc}"})


def page_chat() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown('<div class="app-header">', unsafe_allow_html=True)
    render_header()
    st.markdown("</div>", unsafe_allow_html=True)

    warmup_models()

    if not st.session_state.messages:
        render_welcome()

    for i, msg in enumerate(st.session_state.messages):
        render_message(msg, i)

    pending = st.session_state.pop("pending_question", None)
    if prompt := (pending or st.chat_input("Message Performance AI…")):
        run_chat_turn(prompt)
        st.rerun()


def page_settings() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    if st.button("← Back to chat", type="primary"):
        st.session_state.nav = "Chat"
        st.rerun()

    st.markdown("### Settings")
    ollama: OllamaCascadeClient = st.session_state.ollama

    tab_model, tab_filters, tab_rag, tab_charts, tab_saved, tab_system = st.tabs(
        ["🤖 Model", "🔍 Filters", "📚 Knowledge", "📈 Charts", "⭐ Saved", "🛠 System"]
    )

    with tab_model:
        label = st.selectbox("Model mode", list(MODEL_MODE_OPTIONS.keys()),
                             index=list(MODEL_MODE_OPTIONS.values()).index(st.session_state.model_mode))
        st.session_state.model_mode = MODEL_MODE_OPTIONS[label]
        st.caption(f"Primary `{ollama.primary_model}` · Fallback `{ollama.fallback_model}`")
        if st.button("Load models into memory", type="primary", use_container_width=True):
            st.session_state.models_warmed = False
            with st.spinner("Loading…"):
                warmed = ollama.warmup(st.session_state.model_mode)
            st.session_state.models_warmed = bool(warmed)
            st.success(f"Ready: {', '.join(warmed)}") if warmed else st.warning("Check Ollama is running.")
        if st.button("Check Ollama health", use_container_width=True):
            st.json(ollama.check_health())

    with tab_filters:
        st.caption("Off by default — all sites and all dates are used until you enable a filter below.")
        sites = load_sites()
        opts = ["All sites"] + [s["site_name"] for s in sites]
        keymap = {s["site_name"]: s["site_key"] for s in sites}
        st.session_state.filter_apply_site = st.toggle("Filter by site", st.session_state.filter_apply_site)
        idx = opts.index(st.session_state.filter_site_name) if st.session_state.filter_site_name in opts else 0
        site = st.selectbox("Site", opts, index=idx, disabled=not st.session_state.filter_apply_site)
        if st.session_state.filter_apply_site and site != "All sites":
            st.session_state.filter_site_name, st.session_state.filter_site_key = site, keymap.get(site)
        else:
            st.session_state.filter_site_name = st.session_state.filter_site_key = None
        st.session_state.filter_apply_dates = st.toggle("Filter by date", st.session_state.filter_apply_dates)
        c1, c2 = st.columns(2)
        s, e = default_date_range(5)
        with c1:
            st.session_state.filter_date_start = st.date_input(
                "From", st.session_state.filter_date_start or s, disabled=not st.session_state.filter_apply_dates)
        with c2:
            st.session_state.filter_date_end = st.date_input(
                "To", st.session_state.filter_date_end or e, disabled=not st.session_state.filter_apply_dates)
        f = build_filters()
        if f.is_active():
            st.info(f"Active filters: {f.summary()}")
        else:
            st.success("No filters — using all data")

    with tab_rag:
        st.session_state.use_rag = st.toggle("Enable RAG", st.session_state.use_rag,
                                              help="Retrieve only relevant schema per query")
        st.session_state.rag_top_k = st.slider("Context chunks", 3, 10, st.session_state.rag_top_k,
                                                disabled=not st.session_state.use_rag)

    with tab_charts:
        st.session_state.strict_grounded_answers = st.toggle(
            "Grounded answers only",
            st.session_state.strict_grounded_answers,
            help="Show tables copied from MongoDB tool output. The model cannot rename or invent error types.",
        )
        st.session_state.force_builtin_plots = st.toggle(
            "Built-in charts only",
            st.session_state.force_builtin_plots,
            help="Use reliable Plotly templates instead of LLM-generated plot code (recommended).",
        )
        st.session_state.auto_chart_with_data = st.toggle(
            "Attach chart to data answers",
            st.session_state.auto_chart_with_data,
            help='Also draw a chart when you ask about errors, slides, or stoppages — even without saying "plot".',
            disabled=not st.session_state.force_builtin_plots,
        )
        if st.session_state.strict_grounded_answers:
            st.caption("Data answers come straight from query results — no paraphrased counts.")
        if st.session_state.force_builtin_plots:
            st.caption('Say "plot …" for charts, or enable attach chart above.')

    with tab_saved:
        if st.button("Save last question", disabled=not st.session_state.last_user_query, use_container_width=True):
            save_query(st.session_state.last_user_query,
                       site_key=st.session_state.filter_site_key,
                       site_name=st.session_state.filter_site_name,
                       date_start=str(st.session_state.filter_date_start) if st.session_state.filter_apply_dates else None,
                       date_end=str(st.session_state.filter_date_end) if st.session_state.filter_apply_dates else None)
            st.toast("Saved!")
            st.rerun()
        for q in load_queries()[:15]:
            c1, c2 = st.columns([6, 1])
            if c1.button(q["query"][:55], key=f"sq_{q['id']}", use_container_width=True):
                st.session_state.pending_question = q["query"]
                st.session_state.nav = "Chat"
                st.rerun()
            if c2.button("✕", key=f"del_{q['id']}"):
                delete_query(q["id"])
                st.rerun()

    with tab_system:
        st.markdown("Connected to **`test_db2`** on MongoDB")
        if st.button("Clear all chat history", use_container_width=True):
            st.session_state.messages = []
            st.session_state.bot.reset()
            st.toast("Cleared")
            st.rerun()


def main() -> None:
    init_session_state()
    if st.session_state.nav == "Settings":
        page_settings()
    else:
        page_chat()


if __name__ == "__main__":
    main()
