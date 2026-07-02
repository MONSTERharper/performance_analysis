"""Minimal Streamlit chat for querying test_db2 with a local qwen2.5 model."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from chatbot.agent import Chatbot
from chatbot.ollama_client import OLLAMA_MODEL

st.set_page_config(page_title="test_db2 Assistant", page_icon="🔬", layout="centered")

if "bot" not in st.session_state:
    st.session_state.bot = Chatbot()
if "history" not in st.session_state:
    st.session_state.history = []

col1, col2 = st.columns([5, 1])
with col1:
    st.title("test_db2 Assistant")
    st.caption(f"Ask about scanner performance data · model: `{OLLAMA_MODEL}`")
with col2:
    st.write("")
    if st.button("New chat", use_container_width=True):
        st.session_state.history = []
        st.session_state.bot.reset()
        st.rerun()


def render_rows(rows: list[dict] | None, collection: str | None) -> None:
    if not rows:
        return
    with st.expander(f"Data from `{collection or 'query'}` ({len(rows)} rows)"):
        st.dataframe(pd.DataFrame(rows), use_container_width=True)


for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            render_rows(msg.get("rows"), msg.get("collection"))
        st.markdown(msg["content"])


if prompt := st.chat_input("Ask about test_db2…"):
    st.session_state.history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        status = st.empty()
        try:
            answer = st.session_state.bot.ask(
                prompt, on_status=lambda s: status.markdown(f"_{s}_")
            )
            status.empty()
            render_rows(answer.rows, answer.collection)
            st.markdown(answer.content)
            st.session_state.history.append({
                "role": "assistant",
                "content": answer.content,
                "rows": answer.rows,
                "collection": answer.collection,
            })
        except Exception as exc:
            status.empty()
            st.error(f"Error: {exc}")
            st.session_state.history.append({"role": "assistant", "content": f"Error: {exc}"})
