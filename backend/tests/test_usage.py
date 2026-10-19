"""G3: real token telemetry. Provider usage (both Groq/OpenAI shapes) is parsed, summed across Critic retries,
and tagged source="provider"; the simulator stays source="estimate"."""
import json

import httpx
import pytest

from app.config import Settings
from app.llm.base import LLMRequest, Usage
from app.llm.groq_client import GroqClient
from tests.live_helpers import FakeGroq, by_type, live_client, race_events, sse_body


async def collect(agen):
    return [x async for x in agen]


def _client(handler) -> GroqClient:
    return GroqClient(Settings(groq_api_key="k", sim_time_scale=0.0), transport=httpx.MockTransport(handler))


def _req() -> LLMRequest:
    return LLMRequest(role="naive", tier="70b", query="hello", context_mode="none")


@pytest.mark.parametrize("shape", ["usage", "x_groq"])
async def test_both_usage_shapes_are_parsed_from_the_final_chunk(shape):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=sse_body(["Hel", "lo"], (321, 17), shape))

    out = await collect(_client(handler).stream(_req()))
    assert "".join(x for x in out if isinstance(x, str)) == "Hello"
    usage = [x for x in out if isinstance(x, Usage)]
    assert usage == [Usage(321, 17, "llama-3.3-70b-versatile", "provider")]
    assert seen["body"]["stream_options"] == {"include_usage": True}


async def test_no_usage_in_stream_yields_none_so_the_caller_estimates():
    out = await collect(_client(lambda r: httpx.Response(200, content=sse_body(["a"], None))).stream(_req()))
    assert not any(isinstance(x, Usage) for x in out)


async def test_usage_chunk_with_empty_choices_does_not_break_parsing():
    body = sse_body(["x"], (5, 1))
    assert b'"choices": []' in body
    out = await collect(_client(lambda r: httpx.Response(200, content=body)).stream(_req()))
    assert [x for x in out if isinstance(x, str)] == ["x"]


def test_live_naive_reports_provider_usage_exactly():
    fake = FakeGroq(usage=(4321, 123))
    with live_client(fake) as c:
        ev = race_events(c, "naive", race_id="race-usage-0001", context_mode="none")
    u = by_type(ev, "done")[0]["usage"]
    assert (u["prompt_tokens"], u["completion_tokens"], u["source"]) == (4321, 123, "provider")
    assert u["tier"] == "70b" and u["cost_usd"] == pytest.approx((4321 + 123) / 1e6 * 15.0)


def test_8b_tier_cost_uses_the_configured_ratio():
    fake = FakeGroq(usage=(1000, 0))
    with live_client(fake, cost_ratio_8b=0.5) as c:
        ev = race_events(c, "naive", race_id="race-usage-0002", model_mode="8b")
    u = by_type(ev, "done")[0]["usage"]
    assert u["tier"] == "8b" and u["cost_usd"] == pytest.approx(1000 / 1e6 * 15.0 * 0.5)
    assert fake.calls[0]["model"] == "llama-3.1-8b-instant"


def test_critic_retry_attempts_are_summed_with_real_usage():
    good = json.dumps({"kind": "faq", "answer": "On-call engineers receive a stipend of $350 per week.",
                       "citations": [], "confidence": 0.9})

    def answer(body, n_gen):  # first draft is not JSON -> the Critic rejects it -> retry with feedback
        return "I think it is about 350 dollars." if n_gen == 1 else good

    fake = FakeGroq(usage=(1000, 40), answer=answer)
    with live_client(fake) as c:
        ev = race_events(c, "engineered", race_id="race-usage-0003")
    critics = [n for n in by_type(ev, "node_end") if n["node"] == "critic"]
    assert [x["attempt"] for x in critics] == [0, 1] and critics[0]["data"]["retry_requested"] is True
    gens = [n for n in by_type(ev, "node_end") if n["node"] == "generator"]
    assert [g["data"]["usage"]["source"] for g in gens] == ["provider", "provider"]
    u = by_type(ev, "done")[0]["usage"]
    assert (u["prompt_tokens"], u["completion_tokens"], u["source"]) == (2000, 80, "provider")
    # the retry's prompt carried the verifier feedback
    assert "rejected by a verifier" in fake.calls[1]["messages"][1]["content"]


def test_demo_mode_usage_is_an_estimate():
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.live_helpers import live_settings

    with TestClient(create_app(live_settings(groq_api_key=None))) as c:
        for side in ("naive", "engineered"):
            u = by_type(race_events(c, side), "done")[0]["usage"]
            assert u["source"] == "estimate" and u["prompt_tokens"] > 0
