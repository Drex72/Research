from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any, Protocol

from .config import CONFIG, DECODE, MODEL
from .schemas import ModelReply
from .settings import DecodeSettings


class ChatRuntime(Protocol):
    def chat(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> ModelReply: ...


class OllamaClient:
    def __init__(
        self,
        base_url: str = CONFIG.runtime_base_url,
        model: str = MODEL,
        timeout: int = CONFIG.runtime_timeout_seconds,
        decode: DecodeSettings = DECODE,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.decode = decode

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="GET" if body is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"local model request failed: {type(exc).__name__}") from exc

    def version(self) -> str:
        return str(self._request("/api/version").get("version", ""))

    def model_digest(self) -> str:
        data = self._request("/api/tags")
        for model in data.get("models", []):
            if model.get("name") == self.model:
                return str(model.get("digest", ""))
        raise RuntimeError("configured local model is not installed")

    def chat(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> ModelReply:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": self.decode.think,
            "format": schema,
            "options": {
                "temperature": self.decode.temperature,
                "seed": self.decode.seed,
                "num_ctx": self.decode.num_ctx,
                "num_predict": self.decode.num_predict,
            },
        }
        data = self._request("/api/chat", payload)
        content = data.get("message", {}).get("content", "")
        if not isinstance(content, str) or not content:
            raise RuntimeError("local model returned empty content")
        return ModelReply(
            content=content,
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
            total_duration_ns=int(data.get("total_duration", 0)),
        )


class ScriptedClient:
    """Deterministic runtime used by tests."""

    def __init__(self, replies: list[dict[str, Any]]):
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> ModelReply:
        if not self.replies:
            raise RuntimeError("no scripted reply available")
        self.calls.append({"messages": messages, "schema": schema})
        value = self.replies.pop(0)
        return ModelReply(json.dumps(value), 1, 1, 1)
