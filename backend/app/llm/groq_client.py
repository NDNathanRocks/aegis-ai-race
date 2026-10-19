"""Groq (OpenAI-compatible) streaming chat client.

The API key lives only in the Authorization header built here; it is never put in an event, a log line or an
exception message (errors carry the HTTP status and a few allow-listed rate-limit headers only).
"""
import json
from collections.abc import AsyncIterator, Callable, Mapping

import httpx

from app.config import Settings
from app.llm.base import LLMRequest, LLMUnavailable, Usage, build_messages

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
RATE_HEADERS = (
    "retry-after",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-tokens",
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
)


def rate_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {k: headers[k] for k in RATE_HEADERS if k in headers}


def _usage_from(obj: dict | None, model: str) -> Usage | None:
    if not isinstance(obj, dict):
        return None
    u = obj.get("usage")
    if not isinstance(u, dict) and isinstance(obj.get("x_groq"), dict):
        u = obj["x_groq"].get("usage")  # Groq nests usage here on the final chunk
    if not isinstance(u, dict) or "prompt_tokens" not in u or "completion_tokens" not in u:
        return None
    try:
        return Usage(int(u["prompt_tokens"]), int(u["completion_tokens"]), model, "provider")
    except (TypeError, ValueError):
        return None


class GroqClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._transport = transport

    def model_for(self, req: LLMRequest) -> str:
        """The model id comes from the server-side tier allowlist, never from client input."""
        return self._settings.groq_heavy_model if req.tier == "70b" else self._settings.groq_fast_model

    async def stream(
        self, req: LLMRequest, on_headers: Callable[[str, dict[str, str]], None] | None = None
    ) -> AsyncIterator[str | Usage]:
        if not self._settings.groq_api_key:
            raise LLMUnavailable("no_key")
        model = self.model_for(req)
        body = {
            "model": model,
            "messages": build_messages(req),
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": 0.2,
            "max_tokens": 700,
        }
        if model.startswith("openai/gpt-oss"):
            # Reasoning models spend max_tokens (and the TPM budget) on hidden reasoning before the answer.
            body["reasoning_effort"] = "low"
            body["max_tokens"] = 1000
        if req.role == "generator":
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._settings.groq_api_key}"}
        usage: Usage | None = None
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0), transport=self._transport) as client:
                async with client.stream("POST", GROQ_URL, json=body, headers=headers) as resp:
                    rh = rate_headers(resp.headers)
                    if on_headers:
                        on_headers(model, rh)
                    if resp.status_code == 429:
                        await resp.aread()
                        try:
                            ra = float(resp.headers.get("retry-after", ""))
                        except ValueError:
                            ra = None
                        raise LLMUnavailable("rate_limited", "HTTP 429", status=429, retry_after=ra, headers=rh)
                    if resp.status_code >= 400:
                        await resp.aread()
                        raise LLMUnavailable("upstream_error", f"HTTP {resp.status_code}", status=resp.status_code, headers=rh)
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        usage = _usage_from(chunk, model) or usage
                        try:
                            delta = chunk["choices"][0]["delta"].get("content")
                        except (KeyError, IndexError, TypeError):
                            continue  # the usage-only chunk has an empty `choices`
                        if delta:
                            yield delta
        except httpx.TimeoutException as e:
            raise LLMUnavailable("timeout", type(e).__name__) from e
        except httpx.HTTPError as e:
            raise LLMUnavailable("upstream_error", type(e).__name__) from e
        if usage is not None:
            yield usage
