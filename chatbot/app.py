"""Streamlit web app — Performance AI chat over test_db2.

Layout: persistent left sidebar (controls) + centered chat column (conversation).
"""

from __future__ import annotations

import sys
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
from chatbot.ollama_client import OLLAMA_NUM_CTX, OllamaCascadeClient
from chatbot.saved_queries import delete_query, load_queries, save_query

st.set_page_config(
    page_title="Performance AI",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

MODEL_MODE_OPTIONS = {
    "Auto (DeepSeek → Qwen)": "auto",
    "DeepSeek only": "deepseek",
    "Qwen only": "qwen",
}

STARTER_PROMPTS = [
    ("📈", "Slides trend", "Plot total slides scanned day-wise for the last 5 weeks"),
    ("⏱️", "Load times", "Plot average load duration by site"),
    ("⚠️", "Top errors", "What are the top 10 error codes?"),
    ("📋", "Raw data", "Show raw scanner stoppages as a table"),
    ("🛑", "Stoppages", "Which sites have the most scanner stoppages?"),
    ("🗂️", "Collections", "List all collections in the database"),
]

CSS = """
<style>
    #MainMenu, footer {visibility: hidden;}
    header[data-testid="stHeader"] {background: transparent;}

    /* Center + constrain the main chat column for readability */
    .main .block-container {
        max-width: 860px;
        padding-top: 1.25rem;
        padding-bottom: 6rem;
    }

    /* Sidebar polish */
    section[data-testid="stSidebar"] {
        border-right: 1px solid rgba(128,128,128,0.15);
    }
    .brand {display: flex; align-items: center; gap: 10px; margin: 0.25rem 0 0.5rem 0;}
    .brand-logo {
        width: 34px; height: 34px; border-radius: 9px;
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        display: flex; align-items: center; justify-content: center; font-size: 18px;
    }
    .brand-name {font-size: 1.05rem; font-weight: 700; line-height: 1.1;}
    .brand-sub {font-size: 0.72rem; opacity: 0.55;}

    .status-dot {height: 8px; width: 8px; border-radius: 50%; display: inline-block; margin-right: 6px;}
    .dot-ok {background: #22c55e;}
    .dot-warn {background: #f59e0b;}
    .dot-off {background: #ef4444;}
    .status-line {font-size: 0.8rem; opacity: 0.8; margin: 2px 0;}

    /* Chat header */
    .chat-head {
        display: flex; justify-content: space-between; align-items: center;
        margin-bottom: 0.75rem;
    }
    .chat-title {font-size: 1.35rem; font-weight: 700; margin: 0;}
    .filter-chip {
        display: inline-block; font-size: 0.75rem; padding: 3px 12px;
        border-radius: 999px; background: rgba(99,102,241,0.14); color: #6366f1;
        font-weight: 500;
    }

    /* Status pill during generation */
    .status-pill {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 6px 14px; border-radius: 999px;
        background: rgba(99,102,241,0.12); color: #6366f1;
        font-size: 0.82rem; font-weight: 500; margin: 0.25rem 0 0.6rem 0;
    }

    /* Welcome */
    .welcome {text-align: center; padding: 2rem 0 1rem 0;}
    .welcome h2 {font-size: 1.7rem; font-weight: 700; margin-bottom: 0.35rem;}
    .welcome p {opacity: 0.6; font-size: 0.95rem; margin-bottom: 0.5rem;}

    /* Chat message bubbles */
    div[data-testid="stChatMessage"] {
        border-radius: 14px; padding: 0.4rem 0.9rem !important; margin-bottom: 0.3rem;
    }

    .stButton>button {border-radius: 10px;}
</style>
"""


def init_session_state() -> None:
    start, end = default_date_range(5)

    # One-time migration: old sessions had the date filter on by default.
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
        "filter_site_key": None,
        "filter_site_name": None,
        "filter_date_start": start,
        "filter_date_end": end,
        "filter_apply_site": False,
        "filter_apply_dates": False,
        "last_user_query": "",
        "use_rag": True,
        "rag_top_k": 3,
        "strict_grounded_answers": True,
        "force_builtin_plots": True,
        "auto_chart_with_data": False,
        "models_warmed": False,
        "health": None,
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


# --------------------------------------------------------------------------- #
# Rendering helpers
# --------------------------------------------------------------------------- #
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
    st.dataframe(df, use_container_width=True, height=min(360, 35 * len(df) + 38))


def render_exports(msg: dict, key: str) -> None:
    buttons: list[tuple] = []
    if msg.get("raw_data"):
        buttons.append(("⬇ CSV", records_to_csv(msg["raw_data"]), "data.csv", "text/csv"))
        buttons.append(("⬇ JSON", records_to_json(msg["raw_data"]), "data.json", "application/json"))
    if msg.get("figure_json"):
        buttons.append(("⬇ HTML", figure_to_html(msg["figure_json"]), "chart.html", "text/html"))
        png = figure_to_png_bytes(msg["figure_json"])
        if png:
            buttons.append(("⬇ PNG", png, "chart.png", "image/png"))
    if msg.get("content"):
        buttons.append(("⬇ TXT", content_to_txt(msg["content"]), "response.txt", "text/plain"))

    if not buttons:
        return
    cols = st.columns(len(buttons))
    for col, (label, data, fname, mime) in zip(cols, buttons):
        col.download_button(label, data, file_name=fname, mime=mime, key=f"{key}_{fname}")


def render_message(msg: dict, index: int) -> None:
    avatar = "🧑‍💻" if msg["role"] == "user" else "🔬"
    with st.chat_message(msg["role"], avatar=avatar):
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
                        st.caption(f"Answer source: {msg['model']}")
                    if msg.get("tools"):
                        st.caption(f"Steps: {', '.join(msg['tools'])}")
        else:
            st.markdown(msg["content"])


def render_welcome() -> None:
    st.markdown(
        """
        <div class="welcome">
            <h2>What would you like to analyze?</h2>
            <p>Ask about scanner performance, request charts, or export raw data from <code>test_db2</code>.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(3)
    for i, (icon, label, query) in enumerate(STARTER_PROMPTS):
        if cols[i % 3].button(f"{icon}  {label}", key=f"chip_{i}", use_container_width=True):
            st.session_state.pending_question = query
            st.rerun()


# --------------------------------------------------------------------------- #
# Model / connection status
# --------------------------------------------------------------------------- #
def warmup_models() -> None:
    if st.session_state.models_warmed:
        return
    ollama: OllamaCascadeClient = st.session_state.ollama
    with st.spinner("Preparing models (first time only)…"):
        ollama.warmup(st.session_state.model_mode)
    st.session_state.models_warmed = True


def _status_line(ok: bool | None, ok_text: str, off_text: str, warn: bool = False) -> str:
    if ok is None:
        dot = "dot-warn"
        text = "checking…"
    elif ok:
        dot = "dot-ok"
        text = ok_text
    else:
        dot = "dot-warn" if warn else "dot-off"
        text = off_text
    return f'<div class="status-line"><span class="status-dot {dot}"></span>{text}</div>'


# --------------------------------------------------------------------------- #
# Sidebar (all controls live here — this is the "web app" chrome)
# --------------------------------------------------------------------------- #
def render_sidebar() -> None:
    ollama: OllamaCascadeClient = st.session_state.ollama

    with st.sidebar:
        st.markdown(
            '<div class="brand">'
            '<div class="brand-logo">🔬</div>'
            '<div><div class="brand-name">Performance AI</div>'
            '<div class="brand-sub">Scanner analytics · test_db2</div></div>'
            "</div>",
            unsafe_allow_html=True,
        )

        if st.button("＋  New chat", use_container_width=True, type="primary"):
            st.session_state.messages = []
            st.session_state.bot.reset()
            st.rerun()

        # Live status block
        health = st.session_state.health
        model_ok = st.session_state.models_warmed or (health or {}).get("primary_available")
        st.markdown(
            _status_line(
                (health or {}).get("ollama_reachable") if health else None,
                "Ollama connected",
                "Ollama unreachable",
            )
            + _status_line(
                bool(model_ok) if (health or st.session_state.models_warmed) else None,
                f"Model ready · {ollama.primary_model}",
                "Model not loaded",
                warn=True,
            ),
            unsafe_allow_html=True,
        )

        st.divider()

        _sidebar_filters()
        _sidebar_charts()
        _sidebar_model(ollama)
        _sidebar_knowledge()
        _sidebar_saved()
        _sidebar_system(ollama)


def _sidebar_filters() -> None:
    active = build_filters().is_active()
    with st.expander("🔍  Filters" + ("  •  on" if active else ""), expanded=False):
        st.caption("Off by default — all sites & all dates until enabled.")
        try:
            sites = load_sites()
        except Exception as exc:
            st.warning(f"Couldn't load sites: {exc}")
            sites = []
        opts = ["All sites"] + [s["site_name"] for s in sites]
        keymap = {s["site_name"]: s["site_key"] for s in sites}

        st.session_state.filter_apply_site = st.toggle(
            "Filter by site", st.session_state.filter_apply_site
        )
        idx = opts.index(st.session_state.filter_site_name) if st.session_state.filter_site_name in opts else 0
        site = st.selectbox("Site", opts, index=idx, disabled=not st.session_state.filter_apply_site)
        if st.session_state.filter_apply_site and site != "All sites":
            st.session_state.filter_site_name = site
            st.session_state.filter_site_key = keymap.get(site)
        else:
            st.session_state.filter_site_name = None
            st.session_state.filter_site_key = None

        st.session_state.filter_apply_dates = st.toggle(
            "Filter by date", st.session_state.filter_apply_dates
        )
        s, e = default_date_range(5)
        c1, c2 = st.columns(2)
        with c1:
            st.session_state.filter_date_start = st.date_input(
                "From", st.session_state.filter_date_start or s,
                disabled=not st.session_state.filter_apply_dates,
            )
        with c2:
            st.session_state.filter_date_end = st.date_input(
                "To", st.session_state.filter_date_end or e,
                disabled=not st.session_state.filter_apply_dates,
            )


def _sidebar_charts() -> None:
    with st.expander("📈  Charts & answers", expanded=False):
        st.session_state.strict_grounded_answers = st.toggle(
            "Grounded answers only",
            st.session_state.strict_grounded_answers,
            help="Answers are built straight from MongoDB results. The model cannot rename or invent values.",
        )
        st.session_state.force_builtin_plots = st.toggle(
            "Built-in charts only",
            st.session_state.force_builtin_plots,
            help="Use reliable Plotly templates instead of LLM-generated plot code (recommended).",
        )
        st.session_state.auto_chart_with_data = st.toggle(
            "Attach chart to data answers",
            st.session_state.auto_chart_with_data,
            help='Also draw a chart for error/slide/stoppage questions, even without saying "plot".',
            disabled=not st.session_state.force_builtin_plots,
        )


def _sidebar_model(ollama: OllamaCascadeClient) -> None:
    with st.expander("🤖  Model", expanded=False):
        current_label = next(
            (k for k, v in MODEL_MODE_OPTIONS.items() if v == st.session_state.model_mode),
            list(MODEL_MODE_OPTIONS.keys())[0],
        )
        label = st.selectbox(
            "Model mode",
            list(MODEL_MODE_OPTIONS.keys()),
            index=list(MODEL_MODE_OPTIONS.keys()).index(current_label),
        )
        st.session_state.model_mode = MODEL_MODE_OPTIONS[label]
        st.caption(f"Primary `{ollama.primary_model}` · Fallback `{ollama.fallback_model}`")
        if st.button("Load models into memory", use_container_width=True):
            st.session_state.models_warmed = False
            with st.spinner("Loading…"):
                warmed = ollama.warmup(st.session_state.model_mode)
            st.session_state.models_warmed = bool(warmed)
            if warmed:
                st.success(f"Ready: {', '.join(warmed)}")
            else:
                st.warning("Check that Ollama is running.")


def _sidebar_knowledge() -> None:
    with st.expander("📚  Knowledge (RAG)", expanded=False):
        st.session_state.use_rag = st.toggle(
            "Enable RAG", st.session_state.use_rag,
            help="Retrieve only relevant schema per query (smaller prompts).",
        )
        st.session_state.rag_top_k = st.slider(
            "Context chunks", 3, 10, st.session_state.rag_top_k,
            disabled=not st.session_state.use_rag,
        )


def _sidebar_saved() -> None:
    with st.expander("⭐  Saved queries", expanded=False):
        if st.button(
            "Save last question",
            disabled=not st.session_state.last_user_query,
            use_container_width=True,
        ):
            save_query(
                st.session_state.last_user_query,
                site_key=st.session_state.filter_site_key,
                site_name=st.session_state.filter_site_name,
                date_start=str(st.session_state.filter_date_start) if st.session_state.filter_apply_dates else None,
                date_end=str(st.session_state.filter_date_end) if st.session_state.filter_apply_dates else None,
            )
            st.toast("Saved!")
            st.rerun()
        try:
            saved = load_queries()[:15]
        except Exception:
            saved = []
        if not saved:
            st.caption("No saved queries yet.")
        for q in saved:
            c1, c2 = st.columns([6, 1])
            if c1.button(q["query"][:48], key=f"sq_{q['id']}", use_container_width=True):
                st.session_state.pending_question = q["query"]
                st.rerun()
            if c2.button("✕", key=f"del_{q['id']}"):
                delete_query(q["id"])
                st.rerun()


def _sidebar_system(ollama: OllamaCascadeClient) -> None:
    with st.expander("🛠  System", expanded=False):
        st.caption("Connected to **`test_db2`** on MongoDB")
        st.caption(f"Prompt budget target (`OLLAMA_NUM_CTX`): **{OLLAMA_NUM_CTX:,}** tokens")
        st.caption(
            "Set this to match the model's real context. Loading a model here (Model tab) "
            "warms it at this size; for a permanent change set `OLLAMA_CONTEXT_LENGTH` on the "
            "Ollama server. Prompts are auto-trimmed to fit, so overflow won't crash the app."
        )
        if st.button("Check connection & models", use_container_width=True):
            with st.spinner("Pinging Ollama…"):
                st.session_state.health = ollama.check_health()
            st.rerun()
        if st.session_state.health:
            st.json(st.session_state.health)
        if st.button("Clear chat history", use_container_width=True):
            st.session_state.messages = []
            st.session_state.bot.reset()
            st.toast("Cleared")
            st.rerun()


# --------------------------------------------------------------------------- #
# Chat turn
# --------------------------------------------------------------------------- #
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


def render_chat_header() -> None:
    filters = build_filters()
    chip = (
        f'<span class="filter-chip">Filtered · {filters.summary()}</span>'
        if filters.is_active()
        else ""
    )
    st.markdown(
        f'<div class="chat-head"><p class="chat-title">Chat</p>{chip}</div>',
        unsafe_allow_html=True,
    )


def main() -> None:
    init_session_state()
    st.markdown(CSS, unsafe_allow_html=True)

    render_sidebar()
    warmup_models()

    render_chat_header()

    if not st.session_state.messages:
        render_welcome()

    for i, msg in enumerate(st.session_state.messages):
        render_message(msg, i)

    pending = st.session_state.pop("pending_question", None)
    if prompt := (pending or st.chat_input("Message Performance AI…")):
        run_chat_turn(prompt)
        st.rerun()


if __name__ == "__main__":
    main()
