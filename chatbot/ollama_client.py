"""Ollama client with primary → fallback model cascade and model warm-up."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable, Literal

from dotenv import load_dotenv
from openai import OpenAI
from openai import APIConnectionError, APIStatusError, APITimeoutError, NotFoundError

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_PRIMARY_MODEL = os.getenv("OLLAMA_PRIMARY_MODEL", "deepseek-r1:14b")
OLLAMA_FALLBACK_MODEL = os.getenv("OLLAMA_FALLBACK_MODEL", "qwen2.5:14b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "60m")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))

ModelMode = Literal["auto", "deepseek", "qwen"]


class OllamaCascadeClient:
    """Try primary model first; fall back to secondary on failure."""

    def __init__(
        self,
        primary_model: str | None = None,
        fallback_model: str | None = None,
        base_url: str | None = None,
    ):
        self.primary_model = primary_model or OLLAMA_PRIMARY_MODEL
        self.fallback_model = fallback_model or OLLAMA_FALLBACK_MODEL
        self.base_url = base_url or OLLAMA_BASE_URL
        # Native Ollama API base (strip the OpenAI-compat "/v1" *suffix* only —
        # rstrip("/v1") would wrongly eat trailing digits like a port ":11431").
        self._api_base = self.base_url.rstrip("/").removesuffix("/v1").rstrip("/")
        self._client = OpenAI(
            base_url=self.base_url,
            api_key="ollama",
            timeout=OLLAMA_TIMEOUT,
        )
        self._loaded_models: set[str] = set()

    def _models_for_mode(self, model_mode: ModelMode) -> list[str]:
        if model_mode == "deepseek":
            return [self.primary_model]
        if model_mode == "qwen":
            return [self.fallback_model]
        return [self.primary_model, self.fallback_model]

    def list_local_models(self) -> list[str]:
        try:
            models = self._client.models.list()
            return [m.id for m in models.data]
        except Exception:
            return []

    def check_health(self) -> dict:
        reachable = self._ping()
        models = self.list_local_models() if reachable else []
        return {
            "ollama_reachable": reachable,
            "available_models": models,
            "primary_model": self.primary_model,
            "fallback_model": self.fallback_model,
            "primary_available": self.primary_model in models,
            "fallback_available": self.fallback_model in models,
            "loaded_models": sorted(self._loaded_models),
        }

    def _ping(self) -> bool:
        try:
            urllib.request.urlopen(f"{self._api_base}/api/tags", timeout=5)
            return True
        except Exception:
            return False

    def warmup(self, model_mode: ModelMode = "auto", on_status: Callable[[str, str], None] | None = None) -> list[str]:
        """Load models into Ollama memory once. Keeps them warm via keep_alive."""
        warmed = []
        for model in self._models_for_mode(model_mode):
            if model in self._loaded_models:
                continue
            if on_status:
                on_status("warming_model", model)
            try:
                payload = json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "stream": False,
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                    "options": {"num_ctx": OLLAMA_NUM_CTX},
                }).encode()
                req = urllib.request.Request(
                    f"{self._api_base}/api/chat",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT)
                self._loaded_models.add(model)
                warmed.append(model)
            except Exception:
                pass
        return warmed

    def chat_completion(
        self,
        model_mode: ModelMode = "auto",
        on_status: Callable[[str, str], None] | None = None,
        **kwargs: Any,
    ):
        """Return (response, model_used, used_fallback).

        NOTE on context size: Ollama's OpenAI-compatible `/v1` endpoint currently
        IGNORES `num_ctx` (see ollama/ollama#16814). We still forward it (harmless,
        and honored once ollama/ollama#16825 lands), but the real levers are:
          1. `warmup()` loads the model at OLLAMA_NUM_CTX via the native `/api/chat`,
          2. the caller budgets the prompt to fit (see chatbot/context_budget.py),
          3. optionally set `OLLAMA_CONTEXT_LENGTH` on the Ollama server.
        """
        models = self._models_for_mode(model_mode)
        extra_body = {
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "num_ctx": OLLAMA_NUM_CTX,
            "options": {"num_ctx": OLLAMA_NUM_CTX},
        }

        errors: list[str] = []
        for index, model in enumerate(models):
            if model not in self._loaded_models:
                if on_status:
                    on_status("warming_model", model)
            try:
                if index > 0:
                    if on_status:
                        on_status("using_fallback", model)
                response = self._client.chat.completions.create(
                    model=model,
                    extra_body=extra_body,
                    **kwargs,
                )
                self._loaded_models.add(model)
                return response, model, index > 0
            except (APIConnectionError, APITimeoutError, NotFoundError, APIStatusError) as exc:
                errors.append(f"{model}: {exc}")
            except Exception as exc:
                errors.append(f"{model}: {exc}")

        raise RuntimeError(
            f"Model(s) failed for mode '{model_mode}'.\n" + "\n".join(errors)
        )
