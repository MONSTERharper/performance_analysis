"""Minimal Ollama client — a single local model, nothing else."""

from __future__ import annotations

import json
import os
import urllib.request

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "60m")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))


class OllamaClient:
    """Talks to one Ollama model via the OpenAI-compatible API."""

    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.model = model or OLLAMA_MODEL
        self.base_url = base_url or OLLAMA_BASE_URL
        # Native API base (strip only the "/v1" suffix).
        self._api_base = self.base_url.rstrip("/").removesuffix("/v1").rstrip("/")
        self._client = OpenAI(base_url=self.base_url, api_key="ollama", timeout=OLLAMA_TIMEOUT)
        self._warmed = False

    def warmup(self) -> None:
        """Load the model at the desired context window (native API honors num_ctx)."""
        if self._warmed:
            return
        try:
            payload = json.dumps({
                "model": self.model,
                "messages": [{"role": "user", "content": "ok"}],
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
            self._warmed = True
        except Exception:
            pass

    def chat(self, messages: list[dict], tools: list[dict] | None = None, tool_choice: str = "auto"):
        return self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice if tools else None,
            temperature=0.1,
            extra_body={"keep_alive": OLLAMA_KEEP_ALIVE, "options": {"num_ctx": OLLAMA_NUM_CTX}},
        )
