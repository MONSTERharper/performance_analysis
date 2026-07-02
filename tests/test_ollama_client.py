"""OllamaClient wiring: base URL parsing and single-model default."""

from __future__ import annotations

from chatbot.ollama_client import OLLAMA_MODEL, OllamaClient


def test_default_model_is_single():
    client = OllamaClient()
    assert client.model == OLLAMA_MODEL
    assert client.model  # non-empty


def test_api_base_strips_v1_suffix():
    client = OllamaClient(base_url="http://localhost:11434/v1")
    assert client._api_base == "http://localhost:11434"


def test_api_base_handles_trailing_slash():
    client = OllamaClient(base_url="http://host:11434/v1/")
    assert client._api_base == "http://host:11434"


def test_api_base_without_v1():
    client = OllamaClient(base_url="http://host:11434")
    assert client._api_base == "http://host:11434"
