"""Test doubles for the Groq HTTP API (httpx.MockTransport) and a helper that boots the app in 'live' mode."""
import json
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.groq_client import GroqClient
from app.main import create_app
from tests.conftest import parse_sse

FAQ_ANSWER = {
    "kind": "faq",
    "answer": "On-call engineers receive a stipend of $350 per week.",
    "citations": [],
    "confidence": 0.9,
}


def sse_body(deltas: list[str], usage: tuple[int, int] | None = None, shape: str = "usage") -> bytes:
    """An OpenAI/Groq-style streaming body. shape: 'usage' (top-level, own chunk) | 'x_groq' (nested in last chunk)."""
    frames = [{"choices": [{"index": 0, "delta": {"content": d}}]} for d in deltas]
    frames.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    if usage and shape == "usage":
        frames.append({"choices": [], "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1],
                                                 "total_tokens": sum(usage)}})
    elif usage and shape == "x_groq":
        frames[-1]["x_groq"] = {"id": "req_x", "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1],
                                                         "total_tokens": sum(usage)}}
    return ("".join(f"data: {json.dumps(f)}\n\n" for f in frames) + "data: [DONE]\n\n").encode()


class FakeGroq:
    """httpx handler. Records every request; can 429 the first N calls per model or forever."""

    def __init__(
        self,
        *,
        fail_first_per_model: int = 0,
        always_status: int | None = None,
        retry_after: str = "0",
        usage: tuple[int, int] | None = (1000, 50),
        shape: str = "usage",
        answer: Callable[[dict, int], str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        self.fail_first, self.always_status, self.retry_after = fail_first_per_model, always_status, retry_after
        self.usage, self.shape, self.extra = usage, shape, extra_headers or {}
        self.answer = answer
        self.calls: list[dict] = []
        self.auth: list[str] = []
        self._per_model: Counter = Counter()
        self._gen_calls = 0
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        with self._lock:
            self.calls.append(body)
            self.auth.append(request.headers.get("authorization", ""))
            self._per_model[body["model"]] += 1
            n_model = self._per_model[body["model"]]
            is_json = body.get("response_format", {}).get("type") == "json_object"
            if is_json:
                self._gen_calls += 1
            n_gen = self._gen_calls
        if self.always_status or n_model <= self.fail_first:
            return httpx.Response(self.always_status or 429, headers={"retry-after": self.retry_after, **self.extra})
        if self.answer:
            text = self.answer(body, n_gen)
        else:
            text = json.dumps(FAQ_ANSWER) if is_json else "The on-call stipend is about $350 per week."
        pieces = [text[i : i + 24] for i in range(0, len(text), 24)]
        return httpx.Response(
            200, content=sse_body(pieces, self.usage, self.shape),
            headers={"content-type": "text/event-stream", "x-ratelimit-remaining-tokens": "100000",
                     "x-ratelimit-reset-tokens": "1s", **self.extra},
        )


def live_settings(**kw) -> Settings:
    base = dict(
        groq_api_key="gsk_TEST_SECRET_KEY_do_not_leak", redis_url=None, database_url=None, embedding_backend="hashing",
        sim_time_scale=0.0, rate_limit_per_min=10_000, rate_limit_live_per_min=10_000,
        groq_backoff_base_s=0.01, groq_stagger_ms=0, groq_stagger_jitter_ms=0, groq_retry_budget_s=2.0,
    )
    return Settings(**{**base, **kw})


@contextmanager
def live_client(fake: FakeGroq, **settings_kw) -> Iterator[TestClient]:
    """A started TestClient whose gateway talks to `fake` instead of api.groq.com."""
    settings = live_settings(**settings_kw)
    with TestClient(create_app(settings)) as c:
        c.app.state.ctx.llm.groq = GroqClient(settings, transport=httpx.MockTransport(fake))
        yield c


def race_events(client: TestClient, side: str, query: str = "What is the on-call stipend?", **extra):
    with client.stream("POST", f"/api/race/{side}", json={"query": query, **extra}) as r:
        assert r.status_code == 200, r.text
        return parse_sse(r)


def by_type(events, name):
    return [d for e, d in events if e == name]
