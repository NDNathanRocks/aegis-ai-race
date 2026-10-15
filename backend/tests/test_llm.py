import json

import httpx
import pytest

from app.config import Settings
from app.llm.base import LLMRequest, LLMUnavailable, Reset, build_messages
from app.llm.factory import ResilientLLM
from app.llm.groq_client import GroqClient
from app.llm.simulator import SimulatorClient, generator_card
from app.schemas import CARD_MODELS, RetrievedChunk


async def collect(agen) -> list:
    return [x async for x in agen]


def _sse_body(*deltas: str) -> bytes:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': d}}]})}\n\n" for d in deltas]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


def _settings(**kw) -> Settings:
    return Settings(sim_time_scale=0.0, groq_api_key="k", redis_url=None, database_url=None, **kw)


def _naive_req(**kw) -> LLMRequest:
    return LLMRequest(role="naive", tier="70b", query="hello", **kw)


async def test_simulator_is_deterministic_and_instant():
    sim = SimulatorClient(0.0)
    req = _naive_req(preset_id="hallucination_trap")
    a, b = "".join(await collect(sim.stream(req))), "".join(await collect(sim.stream(req)))
    assert a == b and "looks correct" in a


@pytest.mark.parametrize("kind", ["invoice_audit", "triage", "secure_response", "faq"])
def test_simulated_generator_cards_validate_against_their_schema(kind):
    chunk = RetrievedChunk(chunk_id="d#1", doc_id="d", doc_title="Doc", section="s", rrf_score=0.03, rank=1,
                           text="Doc - s\nOn-call engineers receive a stipend of $350 per week.")
    req = LLMRequest(role="generator", tier="8b", query="INV-2291 reset my password", preset_id="hallucination_trap",
                     card_kind=kind, injection_patterns=["role_hijack"], chunks=[chunk])
    CARD_MODELS[kind].model_validate(generator_card(req))


def test_build_messages_naive_has_no_context_and_generator_embeds_schema():
    naive = build_messages(_naive_req())
    assert [m["role"] for m in naive] == ["system", "user"] and naive[1]["content"] == "hello"
    gen = build_messages(LLMRequest(role="generator", tier="8b", query="q", card_kind="triage", feedback=["fix X"]))
    assert "TriageCard" in gen[0]["content"] and "fix X" in gen[1]["content"]


async def test_groq_client_parses_stream_and_sends_auth():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse_body("Hel", "lo"), headers={"content-type": "text/event-stream"})

    client = GroqClient(_settings(), transport=httpx.MockTransport(handler))
    assert "".join(await collect(client.stream(_naive_req()))) == "Hello"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "llama-3.3-70b-versatile" and seen["body"]["stream"] is True


@pytest.mark.parametrize("status,reason", [(429, "rate_limited"), (503, "upstream_error")])
async def test_groq_client_maps_http_errors(status, reason):
    client = GroqClient(_settings(), transport=httpx.MockTransport(lambda r: httpx.Response(status)))
    with pytest.raises(LLMUnavailable) as e:
        await collect(client.stream(_naive_req()))
    assert e.value.reason == reason


async def test_groq_client_maps_timeouts():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    client = GroqClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMUnavailable) as e:
        await collect(client.stream(_naive_req()))
    assert e.value.reason == "timeout"


async def test_no_key_means_demo_mode_without_touching_the_network():
    llm = ResilientLLM(Settings(sim_time_scale=0.0, groq_api_key=None))
    assert llm.mode() == ("demo", "no_key")
    assert "".join(await collect(llm.stream(_naive_req()))).strip()


class _FailAfter:
    """Groq stand-in that yields some tokens then fails."""

    def __init__(self, n_ok: int, reason: str = "upstream_error"):
        self.n_ok, self.reason = n_ok, reason

    async def stream(self, req):
        for i in range(self.n_ok):
            yield f"tok{i} "
        raise LLMUnavailable(self.reason)


async def test_mid_stream_failure_falls_back_with_reset_and_notifies():
    llm = ResilientLLM(_settings(), groq=_FailAfter(2), sim=SimulatorClient(0.0))
    reasons: list[str] = []
    out = await collect(llm.stream(_naive_req(on_fallback=reasons.append)))
    assert out[:2] == ["tok0 ", "tok1 "] and isinstance(out[2], Reset)
    assert "".join(x for x in out[3:] if isinstance(x, str)).strip()
    assert reasons == ["upstream_error"]


async def test_failure_before_first_token_has_no_reset():
    llm = ResilientLLM(_settings(), groq=_FailAfter(0, "rate_limited"), sim=SimulatorClient(0.0))
    out = await collect(llm.stream(_naive_req()))
    assert not any(isinstance(x, Reset) for x in out) and out


async def test_rate_limit_opens_a_cooldown_so_the_next_run_starts_in_demo():
    llm = ResilientLLM(_settings(), groq=_FailAfter(0, "rate_limited"), sim=SimulatorClient(0.0))
    assert llm.mode()[0] == "live"
    await collect(llm.stream(_naive_req()))
    assert llm.mode() == ("demo", "rate_limited")


def test_force_demo_overrides_live():
    assert ResilientLLM(_settings()).mode(force_demo=True) == ("demo", "forced")
