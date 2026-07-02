"""Smoke test: every chatbot module (incl. the Streamlit app) imports cleanly.

Catches syntax errors, bad imports, and undefined names before runtime —
without needing a live MongoDB or Ollama server.
"""

from __future__ import annotations

import importlib

import pytest

MODULES = [
    "config",
    "db.connection",
    "chatbot.events",
    "chatbot.filters",
    "chatbot.intent",
    "chatbot.context_budget",
    "chatbot.grounded_summary",
    "chatbot.query_auto",
    "chatbot.plot_auto",
    "chatbot.rag",
    "chatbot.knowledge_loader",
    "chatbot.mongo_tools",
    "chatbot.export_utils",
    "chatbot.saved_queries",
    "chatbot.ollama_client",
    "chatbot.agent",
    "chatbot.cli",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    assert importlib.import_module(module) is not None


def test_streamlit_app_imports():
    # The Streamlit app calls st.set_page_config at import; that is safe to run.
    assert importlib.import_module("chatbot.app") is not None


def test_agent_public_api():
    from chatbot.agent import PerformanceChatbot

    bot = PerformanceChatbot.__new__(PerformanceChatbot)
    assert hasattr(bot, "chat")
    assert hasattr(bot, "reset")
