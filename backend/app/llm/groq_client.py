"""Groq (OpenAI-compatible) streaming chat client."""
import json
from collections.abc import AsyncIterator

import httpx

from app.config import Settings
from app.llm.base import LLMRequest, LLMUnavailable, Reset, build_messages

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._transport = transport

    def _model(self, req: LLMRequest) -> str:
        return self._settings.groq_heavy_model if req.tier == "70b" else self._settings.groq_fast_model

    async def stream(self, req: LLMRequest) -> AsyncIterator[str | Reset]:
        if not self._settings.groq_api_key:
            raise LLMUnavailable("no_key")
        body = {
            "model": self._model(req),
            "messages": build_messages(req),
            "stream": True,
            "temperature": 0.2,
            "max_tokens": 700,
        }
        if req.role == "generator":
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._settings.groq_api_key}"}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0), transport=self._transport) as client:
                async with client.stream("POST", GROQ_URL, json=body, headers=headers) as resp:
                    if resp.status_code == 429:
                        raise LLMUnavailable("rate_limited", resp.headers.get("retry-after", ""))
                    if resp.status_code >= 400:
                        await resp.aread()
                        raise LLMUnavailable("upstream_error", f"HTTP {resp.status_code}")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            return
                        try:
                            delta = json.loads(data)["choices"][0]["delta"].get("content")
                        except (KeyError, IndexError, json.JSONDecodeError):
                            continue
                        if delta:
                            yield delta
        except httpx.TimeoutException as e:
            raise LLMUnavailable("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise LLMUnavailable("upstream_error", str(e)) from e
