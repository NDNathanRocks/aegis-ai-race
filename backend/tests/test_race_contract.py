"""v2 request/event contract: allowlisted enums, meta v2 fields, payload events, model/context semantics, domains
API, and the security items (no key in any event/log/config, TRUST_PROXY, CORS allowlist)."""
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm.groq_client import GroqClient
from app.main import create_app
from tests.live_helpers import FakeGroq, by_type, live_client, live_settings, race_events

KEY = "gsk_TEST_SECRET_KEY_do_not_leak"


@pytest.fixture(scope="module")
def demo():
    with TestClient(create_app(live_settings(groq_api_key=None))) as c:
        yield c


# --- allowlisted enums / validation ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "body",
    [
        {"query": "q", "domain": "finance"},
        {"query": "q", "model_mode": "gpt-4o"},
        {"query": "q", "model_mode": "llama-3.3-70b-versatile"},  # a real model id is still not an allowed enum value
        {"query": "q", "context_mode": "everything"},
        {"query": "q", "race_id": "short"},
        {"query": "q", "race_id": "has spaces in it!"},
        {"query": "q", "preset_id": "../../etc/passwd"},
        {"query": "q", "preset_id": "travel_hallucination_trap", "domain": "b2b_sla"},  # preset of another domain
        {"query": "q", "variant": "other"},
    ],
)
def test_unknown_enums_and_foreign_presets_are_422(demo, body):
    assert demo.post("/api/race/naive", json=body).status_code == 422
    assert demo.post("/api/race/engineered", json=body).status_code == 422


def test_legacy_b2b_preset_ids_and_alias_are_accepted(demo):
    for pid in ("hallucination_trap", "tier1_triage", "prompt_injection", "semantic_cache"):
        r = race_events(demo, "naive", "What is the on-call stipend?", preset_id=pid, domain="b2b_sla")
        assert r[-1][0] == "done"


def test_client_cannot_inject_a_model_string_into_the_groq_body():
    fake = FakeGroq()
    with live_client(fake) as c:
        body = {"query": "q", "model": "evil-model", "model_mode": "70b", "race_id": "race-model-001x"}
        r = c.post("/api/race/naive", json=body)
        assert r.status_code == 200  # unknown extra field ignored
    assert {b["model"] for b in fake.calls} == {"llama-3.3-70b-versatile"}


# --- meta v2 + race_state -----------------------------------------------------------------------------------------
def test_meta_v2_fields_naive_and_engineered(demo):
    for side in ("naive", "engineered"):
        ev = race_events(demo, side, race_id="race-meta-00001", domain="b2b_sla", model_mode="8b", context_mode="none")
        m = by_type(ev, "meta")[0]
        assert m["domain"] == "b2b_sla" and m["race_id"] == "race-meta-00001"
        assert m["provider"] == "simulator" and m["model_mode"] == "8b" and m["context_mode"] == "none"
        assert m["base_model"] == "llama-3.1-8b-instant" and m["model"] == "llama-3.1-8b-instant"
        assert isinstance(m["kb_tokens"], int) and m["kb_tokens"] > 500
        assert by_type(ev, "race_state")[0] == {**by_type(ev, "race_state")[0], "degraded": False, "provider": "simulator"}


def test_auto_model_mode_naive_70b_engineered_routed(demo):
    n = by_type(race_events(demo, "naive", model_mode="auto"), "meta")[0]
    e = by_type(race_events(demo, "engineered", model_mode="auto"), "meta")[0]
    assert n["model"] == n["base_model"] == "llama-3.3-70b-versatile"
    assert e["base_model"] == "llama-3.3-70b-versatile" and "routed" in e["model"]


@pytest.mark.parametrize("mode,tier", [("70b", "70b"), ("8b", "8b")])
def test_model_mode_forces_the_router_tier_but_reports_its_own_choice(demo, mode, tier):
    ev = race_events(demo, "engineered", "Classify this ticket and set its priority: locked out, reset my password",
                     model_mode=mode)
    router = next(n for n in by_type(ev, "node_end") if n["node"] == "router")["data"]
    assert router["tier"] == tier
    if mode == "70b":
        assert "would pick" in router["reason"]  # the simple ticket would have routed to 8b
    assert by_type(ev, "done")[0]["usage"]["tier"] == tier


def test_auto_lets_the_router_pick(demo):
    ev = race_events(demo, "engineered", "Classify this ticket and set its priority: locked out, reset my password",
                     model_mode="auto")
    router = next(n for n in by_type(ev, "node_end") if n["node"] == "router")["data"]
    assert router["tier"] == "8b" and "forces" not in router["reason"]


# --- payload event -----------------------------------------------------------------------------------------------------
def test_naive_payload_full_kb_vs_none(demo):
    full = by_type(race_events(demo, "naive", context_mode="full_kb"), "payload")
    none = by_type(race_events(demo, "naive", context_mode="none"), "payload")
    assert len(full) == len(none) == 1
    kb = demo.app.state.ctx.domains["b2b_sla"].spec.kb_text
    f, n = full[0], none[0]
    assert f["attempt"] == 0 and f["model"] == "llama-3.3-70b-versatile" and "chunks" not in f
    assert kb in f["messages"][0]["content"] and kb not in n["messages"][0]["content"]
    assert [c["label"] for c in f["composition"]] == ["System prompt", "Full knowledge base", "Question"]
    assert f["token_count"] > n["token_count"] + 400 and f["token_source"] == "estimate"
    assert [m["role"] for m in f["messages"]] == ["system", "user"]
    assert f["messages"][1]["content"] == "What is the on-call stipend?"


def test_engineered_payload_per_attempt_with_chunks_and_feedback(demo):
    from app.presets import PRESETS

    p = PRESETS["hallucination_trap"]  # the simulator's first draft is wrong -> Critic retry -> 2 payloads
    ev = race_events(demo, "engineered", p.query, preset_id=p.id, session_id="payload-sess")
    payloads = by_type(ev, "payload")
    assert [x["attempt"] for x in payloads] == [0, 1]
    first, second = payloads
    assert 1 <= len(first["chunks"]) <= 4 and first["chunks"][0]["rank"] == 1 and "rrf_score" in first["chunks"][0]
    assert first["chunks"] == second["chunks"]
    assert "rejected by a verifier" not in first["messages"][1]["content"]
    assert "rejected by a verifier" in second["messages"][1]["content"]
    assert [c["label"] for c in first["composition"]][0].startswith("System prompt")
    assert sum(c["tokens"] for c in first["composition"]) == pytest.approx(first["token_count"], abs=8)
    for ch in first["chunks"]:  # the chunk ids sent are the chunk ids shown
        assert f"[{ch['chunk_id']}]" in first["messages"][1]["content"]


def test_payload_event_comes_before_the_first_token(demo):
    ev = race_events(demo, "naive")
    names = [e for e, _ in ev]
    assert names.index("payload") < names.index("token")


# --- verdict ---------------------------------------------------------------------------------------------------------------
def test_verdict_event_on_both_sides_before_done(demo):
    from app.presets import PRESETS

    p = PRESETS["hallucination_trap"]
    for side in ("naive", "engineered"):
        ev = race_events(demo, side, p.query, preset_id=p.id, session_id=f"verdict-{side}")
        names = [e for e, _ in ev]
        v = by_type(ev, "verdict")[0]
        assert names.index("verdict") < names.index("done")
        assert set(v) >= {"correct", "required", "forbidden_hits", "key_applies"}
        assert isinstance(v["correct"], bool)


def test_verdict_without_a_preset_has_no_key(demo):
    v = by_type(race_events(demo, "naive", "What is the on-call stipend?"), "verdict")[0]
    assert v["key_applies"] is False and v["required"] == []


# --- domains / kb API -------------------------------------------------------------------------------------------------
def test_domains_endpoint_shape(demo):
    data = demo.get("/api/domains").json()
    assert data, "at least one loaded domain"
    for d in data:
        assert set(d) == {"id", "title", "emoji", "blurb", "kb_tokens", "doc_count", "presets"}
        assert d["kb_tokens"] > 0 and d["doc_count"] > 0
        for p in d["presets"]:
            assert set(p) == {"id", "kind", "title", "tagline", "query", "paraphrase", "card_kind"}


def test_kb_domain_endpoints_and_unknown_domain(demo):
    docs = demo.get("/api/kb/b2b_sla/documents").json()
    assert docs and set(docs[0]) == {"id", "title", "category", "words"}
    assert demo.get(f"/api/kb/b2b_sla/documents/{docs[0]['id']}").json()["text"].startswith("# ")
    assert demo.get("/api/kb/nope/documents").status_code == 404
    assert demo.get("/api/kb/..%2F..%2Fapp/documents").status_code in (404, 422)
    assert demo.get("/api/kb/b2b_sla/documents/missing").status_code == 404


def test_presets_endpoint_keeps_legacy_shape_and_accepts_domain(demo):
    legacy = demo.get("/api/presets").json()
    assert {p["id"] for p in legacy} == {"hallucination_trap", "semantic_cache", "tier1_triage", "prompt_injection"}
    assert demo.get("/api/presets", params={"domain": "nope"}).status_code == 404


def test_cache_namespace_is_per_domain_and_session(demo):
    ctx = demo.app.state.ctx
    a, b = ctx.cache_for("s1", "b2b_sla"), ctx.cache_for("s1", "nutrition")
    assert a is not b and a is ctx.cache_for("s1", "b2b_sla")
    assert ctx.cache_for("s2", "b2b_sla") is not a


# --- security -----------------------------------------------------------------------------------------------------------------
def _raw_sse(client, side, **body) -> str:
    with client.stream("POST", f"/api/race/{side}", json={"query": "What is the on-call stipend?", **body}) as r:
        return "\n".join(r.iter_lines())


@pytest.mark.parametrize("fake_kw", [{}, {"always_status": 429}, {"always_status": 500}])
def test_api_key_never_appears_in_sse_output_config_or_logs(caplog, fake_kw):
    fake = FakeGroq(**fake_kw)
    caplog.set_level(logging.DEBUG)
    with live_client(fake, groq_max_retries=1) as c:
        raw = [_raw_sse(c, s, race_id=f"race-leak-{s[:3]}-{len(fake_kw)}") for s in ("naive", "engineered")]
        rest = [c.get(u).text for u in ("/api/config", "/api/domains", "/api/presets", "/api/health")]
    assert fake.auth and all(a == f"Bearer {KEY}" for a in fake.auth) or not fake.auth
    for blob in raw + rest + [caplog.text]:
        assert KEY not in blob and "gsk_" not in blob and "Authorization" not in blob and "Bearer" not in blob


def test_payload_event_never_contains_the_key():
    with live_client(FakeGroq()) as c:
        for side in ("naive", "engineered"):
            ev = race_events(c, side, race_id=f"race-pay-{side[:3]}-001")
            assert KEY not in str(by_type(ev, "payload"))


def test_rate_limiter_ignores_x_forwarded_for_by_default():
    with TestClient(create_app(live_settings(groq_api_key=None, rate_limit_per_min=2))) as c:
        for i in range(2):
            assert c.post("/api/race/naive", json={"query": "a b"}, headers={"X-Forwarded-For": f"9.9.9.{i}"}).status_code == 200
        # spoofing a fresh address does not evade the limiter
        assert c.post("/api/race/naive", json={"query": "a b"}, headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 429


def test_rate_limiter_honours_x_forwarded_for_with_trust_proxy():
    with TestClient(create_app(live_settings(groq_api_key=None, rate_limit_per_min=1, trust_proxy=True))) as c:
        def post(xff):
            return c.post("/api/race/naive", json={"query": "a b"}, headers={"X-Forwarded-For": xff}).status_code

        assert post("203.0.113.5") == 200
        assert post("203.0.113.5") == 429
        assert post("203.0.113.6") == 200  # a different real client
        # a client-supplied left-most entry cannot shift the identity: the proxy-appended right-most hop wins
        assert post("1.1.1.1, 203.0.113.5") == 429


def test_cors_stays_an_allowlist(demo):
    bad = demo.options("/api/race/naive", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers
    ok = demo.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert demo.get("/api/health", headers={"Origin": "https://evil.example"}).headers.get("access-control-allow-origin") is None


def test_error_events_do_not_echo_upstream_detail():
    def handler(request):
        return httpx.Response(401, text="invalid key gsk_whatever", headers={"x-secret": "nope"})

    settings = live_settings(groq_max_retries=0)
    with live_client(FakeGroq(), groq_max_retries=0) as c:
        c.app.state.ctx.llm.groq = GroqClient(settings, transport=httpx.MockTransport(handler))
        raw = _raw_sse(c, "naive", race_id="race-err-000001")
    assert "invalid key" not in raw and "gsk_whatever" not in raw and "nope" not in raw


# --- Critic on live (non-canned) text ---------------------------------------------------------------------------------
def test_critic_catches_a_realistic_llama_style_wrong_answer_then_accepts_the_retry():
    """First reply: fenced JSON with an invented payout (what a small model produces). The deterministic Critic flags
    the underivable figure, the retry carries that feedback, and the second reply is graded correct by the key."""
    import json
    import re

    from tests.heroes import TRAVEL_HERO

    def answer(body, n_gen):
        cid = re.search(r"\[([a-z0-9_]+#\d+)\]", body["messages"][1]["content"]).group(1)
        card = {
            "kind": "appr_claim", "carrier_size": "large", "delay_hours": 6.5, "delay_cause": "within_control",
            "passengers": 1, "delay_compensation_cad": 4321, "baggage_refund_cad": 70, "total_cad": 4391,
            "rejected_claims": [], "citations": [cid],
        }
        if n_gen > 1:
            card.update(delay_compensation_cad=700, total_cad=770)
        text = json.dumps(card, indent=2)
        return f"Here is the audit you asked for:\n```json\n{text}\n```" if n_gen == 1 else text

    fake = FakeGroq(usage=(2000, 120), answer=answer)
    with live_client(fake) as c:
        ev = race_events(c, "engineered", TRAVEL_HERO, domain="travel_appr", preset_id="travel_hallucination_trap",
                         race_id="race-llama-0001")
    critics = [n["data"] for n in by_type(ev, "node_end") if n["node"] == "critic"]
    assert critics[0]["passed"] is False and critics[0]["retry_requested"] is True
    assert any("4,321" in f for f in critics[0]["flagged_claims"])
    assert critics[1]["passed"] is True
    assert "4,321" in fake.calls[1]["messages"][1]["content"]  # the verifier feedback reached the second prompt
    done = by_type(ev, "done")[0]
    assert done["hallucination_prevented"] is True and done["mode"] == "live"
    assert done["usage"]["prompt_tokens"] == 4000 and done["usage"]["source"] == "provider"
    verdict = by_type(ev, "verdict")[0]
    assert verdict["correct"] is True and verdict["key_applies"] is True
    assert by_type(ev, "card")[0]["card"]["total_cad"] == 770


def test_live_naive_wrong_answer_gets_spans_on_the_final_text_and_a_failing_verdict():
    import re

    from tests.heroes import TRAVEL_HERO

    wrong = ("Good news! EU261 applies to your delay and entitles you to €600. The $300 voucher is optional, so take "
             "the cash. Your two bags cost $70 in fees, so you are owed about €670 in total.")
    fake = FakeGroq(answer=lambda body, n: wrong)
    with live_client(fake) as c:
        ev = race_events(c, "naive", TRAVEL_HERO, domain="travel_appr", preset_id="travel_hallucination_trap",
                         race_id="race-llama-0002")
    text = "".join(t["text"] for t in by_type(ev, "token"))
    assert text == wrong
    v = by_type(ev, "verdict")[0]
    assert v["correct"] is False and v["forbidden_hits"]
    for h in v["forbidden_hits"]:
        s, e = h["span"]
        assert re.search(r"€\s?600|300 voucher|EU\s?261 (applies|entitles)", wrong[s:e])
    claims = by_type(ev, "naive_analysis")[0]["ungrounded_claims"]
    assert claims and all(0 <= c["span"][0] < c["span"][1] <= len(wrong) for c in claims)
