import json

import httpx
import pytest

from app.config import Settings
from app.llm.base import LLMRequest, LLMUnavailable, Reset, Usage, build_messages
from app.llm.gateway import LLMGateway
from app.llm.groq_client import GroqClient
from app.llm.simulator import SimulatorClient, generator_card
from app.schemas import CARD_MODELS, RetrievedChunk
from tests.heroes import TENANCY_HERO, TIER1, TRAVEL_HERO


async def collect(agen) -> list:
    return [x async for x in agen]


def _sse_body(*deltas: str) -> bytes:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': d}}]})}\n\n" for d in deltas]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


def _settings(**kw) -> Settings:
    base = dict(sim_time_scale=0.0, groq_api_key="k", redis_url=None, database_url=None, groq_backoff_base_s=0.0,
                groq_stagger_ms=0, groq_stagger_jitter_ms=0, groq_retry_budget_s=2.0, groq_max_retries=1)
    return Settings(**{**base, **kw})


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


def _gen(card_kind, query, domain, **kw) -> LLMRequest:
    chunk = RetrievedChunk(chunk_id="d#1", doc_id="d", doc_title="Doc", section="s", rrf_score=0.03, rank=1,
                           text="Doc - s" + chr(10) + "Some retrieved text.")
    return LLMRequest(role="generator", tier="70b", query=query, card_kind=card_kind, domain=domain,
                      chunks=[chunk], **kw)


def test_simulator_hero_cards_are_the_correct_answers_for_the_new_domains():
    appr = CARD_MODELS["appr_claim"].model_validate(generator_card(_gen("appr_claim", TRAVEL_HERO, "travel_appr")))
    assert (appr.delay_compensation_cad, appr.baggage_refund_cad, appr.total_cad) == (700, 70, 770)
    assert appr.delay_hours == 6.5 and appr.passengers == 1 and len(appr.rejected_claims) == 2

    t = CARD_MODELS["tenancy_tax"].model_validate(generator_card(_gen("tenancy_tax", TENANCY_HERO, "bc_tenancy_cra")))
    assert (float(t.allowed_increase_pct), float(t.max_increase_cad), float(t.max_new_rent_cad)) == (2.3, 55.2, 2455.2)
    assert t.proposed_increase_lawful is False and t.eviction_notice_valid is False
    assert float(t.tfsa_penalty_cad) == 135.0 and t.tfsa_months == 3


def test_simulated_naive_falls_for_each_domains_trap():
    import re

    sim = SimulatorClient(0.0)

    async def text(domain, kind):
        return "".join(await collect(sim.stream(_naive_req(domain=domain, preset_kind=kind))))

    import asyncio

    travel = asyncio.run(text("travel_appr", "hallucination_trap"))
    assert re.search(r"EU\s?261 applies", travel) and "€600" in travel
    tenancy = asyncio.run(text("bc_tenancy_cra", "hallucination_trap"))
    assert re.search(r"3(\.0)?\s?%", tenancy) and "$72" in tenancy
    for domain in ("travel_appr", "bc_tenancy_cra", "nutrition"):
        for kind in ("tier1_router", "prompt_injection", "hallucination_trap"):
            assert asyncio.run(text(domain, kind)).strip()


def test_can_build_only_for_scenarios_the_demo_can_compute():
    from app.llm.simulator import can_build

    assert can_build("appr_claim", TRAVEL_HERO, None, "travel_appr")
    assert not can_build("appr_claim", "Compensation please, thanks", None, "travel_appr")
    assert can_build("tenancy_tax", TENANCY_HERO, None, "bc_tenancy_cra")
    assert can_build("faq", TIER1["travel_appr"], None, "travel_appr")


def test_build_messages_naive_full_kb_vs_none_and_composition():
    from app.llm.base import build_payload

    full, comp_full = build_payload(_naive_req(context_mode="full_kb", kb_text="KB-LINE " * 50))
    assert "KB-LINE" in full[0]["content"] and [c["label"] for c in comp_full] == [
        "System prompt", "Full knowledge base", "Question"]
    none, comp_none = build_payload(_naive_req(context_mode="none", kb_text="KB-LINE " * 50))
    assert "KB-LINE" not in none[0]["content"] and len(comp_none) == 2
    gen, comp_gen = build_payload(_gen("appr_claim", "q", "travel_appr"))
    assert "appr_claim" in gen[0]["content"] and "rejected_claims" in gen[0]["content"]
    assert comp_gen[1]["label"].startswith("Retrieved chunks")


def test_build_messages_naive_has_no_context_and_generator_embeds_schema():
    naive = build_messages(_naive_req())
    assert [m["role"] for m in naive] == ["system", "user"] and naive[1]["content"] == "hello"
    gen = build_messages(LLMRequest(role="generator", tier="8b", query="q", card_kind="triage", feedback=["fix X"]))
    assert "suggested_queue" in gen[0]["content"] and "fix X" in gen[1]["content"]


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
    llm = LLMGateway(Settings(sim_time_scale=0.0, groq_api_key=None))
    assert llm.mode() == ("demo", "no_key")
    run = llm.run_for("race-nokey-0001")
    out = await collect(llm.stream(run, _naive_req()))
    assert "".join(x for x in out if isinstance(x, str)).strip()
    usage = [x for x in out if isinstance(x, Usage)]
    assert len(usage) == 1 and usage[0].source == "estimate" and not run.degraded


class _FailAfter:
    """Groq stand-in that yields some tokens then fails."""

    def __init__(self, n_ok: int, reason: str = "upstream_error"):
        self.n_ok, self.reason = n_ok, reason
        self.calls = 0

    async def stream(self, req):
        self.calls += 1
        for i in range(self.n_ok):
            yield f"tok{i} "
        raise LLMUnavailable(self.reason)


async def test_mid_stream_failure_retries_then_degrades_with_reset_and_notifies():
    groq = _FailAfter(2)
    llm = LLMGateway(_settings(), groq=groq, sim=SimulatorClient(0.0))
    run, reasons = llm.run_for("race-mid-0001"), []
    out = await collect(llm.stream(run, _naive_req(on_fallback=reasons.append)))
    assert groq.calls == 2  # one retry within the budget, then the race gives up
    assert out[:2] == ["tok0 ", "tok1 "] and any(isinstance(x, Reset) for x in out)
    resets = [i for i, x in enumerate(out) if isinstance(x, Reset)]
    assert "".join(x for x in out[resets[-1] :] if isinstance(x, str)).strip()  # demo text after the last reset
    assert reasons == ["upstream_error"] and run.degraded and run.provider == "simulator"
    assert [x for x in out if isinstance(x, Usage)][-1].source == "estimate"


async def test_failure_before_first_token_has_no_reset():
    llm = LLMGateway(_settings(), groq=_FailAfter(0, "rate_limited"), sim=SimulatorClient(0.0))
    out = await collect(llm.stream(llm.run_for("race-pre-0001"), _naive_req()))
    assert not any(isinstance(x, Reset) for x in out) and out


async def test_rate_limit_is_not_a_sticky_global_cooldown():
    """The old 60 s process-wide cooldown is gone: a degraded race does not poison the next one."""
    groq = _FailAfter(0, "rate_limited")
    llm = LLMGateway(_settings(), groq=groq, sim=SimulatorClient(0.0))
    first = llm.run_for("race-cd-0001")
    await collect(llm.stream(first, _naive_req()))
    assert first.degraded
    second = llm.run_for("race-cd-0002")
    assert second.provider == "groq" and not second.degraded
    assert llm.mode() == ("live", None)


async def test_degraded_run_makes_the_sibling_side_fall_back_too():
    llm = LLMGateway(_settings(), groq=_FailAfter(0, "upstream_error"), sim=SimulatorClient(0.0))
    run = llm.run_for("race-sib-0001")
    await collect(llm.stream(run, _naive_req()))
    reasons: list[str] = []
    gen = LLMRequest(role="generator", tier="70b", query="q", card_kind="faq", on_fallback=reasons.append)
    out = await collect(llm.stream(run, gen))
    assert reasons == ["upstream_error"] and any(isinstance(x, str) for x in out)


def test_force_demo_overrides_live():
    assert LLMGateway(_settings()).mode(force_demo=True) == ("demo", "forced")


def test_compact_schema_keeps_every_field_and_is_smaller():
    import json

    from app.llm.base import compact_schema
    from app.schemas import CARD_MODELS

    for kind, model in CARD_MODELS.items():
        compact = json.loads(compact_schema(kind))
        assert set(compact["properties"]) == set(model.model_json_schema()["properties"]), kind
        assert len(compact_schema(kind)) < len(json.dumps(model.model_json_schema())), kind
