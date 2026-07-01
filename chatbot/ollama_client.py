"""Ollama client with primary → fallback model cascade."""

from __future__ import annotations

import os
from typing import Any, Callable, Literal

from dotenv import load_dotenv
from openai import OpenAI
from openai import APIConnectionError, APIStatusError, APITimeoutError, NotFoundError

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_PRIMARY_MODEL = os.getenv("OLLAMA_PRIMARY_MODEL", "deepseek-r1:14b")
OLLAMA_FALLBACK_MODEL = os.getenv("OLLAMA_FALLBACK_MODEL", "qwen2.5:14b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))

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
        self._client = OpenAI(
            base_url=self.base_url,
            api_key="ollama",
            timeout=OLLAMA_TIMEOUT,
        )

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
        }

    def _ping(self) -> bool:
        try:
            import urllib.request
            base = self.base_url.rstrip("/v1").rstrip("/")
            urllib.request.urlopen(f"{base}/api/tags", timeout=5)
            return True
        except Exception:
            return False

    def chat_completion(
        self,
        model_mode: ModelMode = "auto",
        on_status: Callable[[str, str], None] | None = None,
        **kwargs: Any,
    ):
        """Return (response, model_used, used_fallback)."""
        if model_mode == "deepseek":
            models = [self.primary_model]
        elif model_mode == "qwen":
            models = [self.fallback_model]
        else:
            models = [self.primary_model, self.fallback_model]

        errors: list[str] = []
        for index, model in enumerate(models):
            if on_status:
                on_status("loading_model", model)
            try:
                if index > 0:
                    if on_status:
                        on_status("using_fallback", model)
                response = self._client.chat.completions.create(model=model, **kwargs)
                return response, model, index > 0
            except (APIConnectionError, APITimeoutError, NotFoundError, APIStatusError) as exc:
                errors.append(f"{model}: {exc}")
            except Exception as exc:
                errors.append(f"{model}: {exc}")

        raise RuntimeError(
            f"Model(s) failed for mode '{model_mode}'.\n" + "\n".join(errors)
        )
