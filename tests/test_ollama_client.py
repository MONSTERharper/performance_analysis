"""Tests for OllamaCascadeClient wiring that does not require a live server."""

from __future__ import annotations

import pytest

from chatbot.ollama_client import OllamaCascadeClient


@pytest.mark.parametrize(
    "base_url, expected_api_base",
    [
        ("http://localhost:11434/v1", "http://localhost:11434"),
        ("http://localhost:11434/v1/", "http://localhost:11434"),
        # Regression: a port ending in '1' must not be corrupted by rstrip("/v1").
        ("http://localhost:11431/v1", "http://localhost:11431"),
        ("http://10.10.1.124:11431/v1", "http://10.10.1.124:11431"),
        # No /v1 suffix -> unchanged (minus trailing slash).
        ("http://localhost:11434", "http://localhost:11434"),
    ],
)
def test_api_base_strips_v1_suffix_safely(base_url, expected_api_base):
    client = OllamaCascadeClient(base_url=base_url)
    assert client._api_base == expected_api_base


def test_models_for_mode():
    c = OllamaCascadeClient(primary_model="p", fallback_model="f", base_url="http://x/v1")
    assert c._models_for_mode("deepseek") == ["p"]
    assert c._models_for_mode("qwen") == ["f"]
    assert c._models_for_mode("auto") == ["p", "f"]
