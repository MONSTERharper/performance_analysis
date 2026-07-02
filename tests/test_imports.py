"""Smoke test: every chatbot module (incl. the Streamlit app) imports cleanly."""

from __future__ import annotations

import importlib

import pytest

MODULES = [
    "config",
    "db.connection",
    "chatbot.knowledge_loader",
    "chatbot.mongo_tools",
    "chatbot.ollama_client",
    "chatbot.agent",
    "chatbot.cli",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    assert importlib.import_module(module) is not None


def test_streamlit_app_imports():
    assert importlib.import_module("chatbot.app") is not None


def test_agent_public_api():
    from chatbot.agent import Chatbot

    bot = Chatbot.__new__(Chatbot)
    assert hasattr(bot, "ask")
    assert hasattr(bot, "reset")


def test_tool_definitions_are_read_only():
    from chatbot.mongo_tools import TOOL_DEFINITIONS

    names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    assert names == {
        "list_collections",
        "describe_collection",
        "find_documents",
        "count_documents",
        "aggregate",
    }
