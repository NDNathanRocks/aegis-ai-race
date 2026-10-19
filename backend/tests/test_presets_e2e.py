"""All four challenge presets, both sides, end to end through the SSE API with real embeddings."""
import json
from decimal import Decimal

import pytest

from app.presets import PRESETS

pytestmark = pytest.mark.model

NODE_ORDER = ["router", "cache", "retriever", "generator", "critic", "validator"]


def by_type(events, name):
    return [d for e, d in events if e == name]


def node_ends(events):
    return [d for e, d in events if e == "node_end"]


def done(events):
    return by_type(events, "done")[0]


def test_hallucination_trap_engineered_catches_the_math(run_race):
    p = PRESETS["hallucination_trap"]
    ev = run_race("engineered", p.query, p.id)

    ends = node_ends(ev)
    assert [n["node"] for n in ends if n["node"] != "generator" and n["node"] != "critic"] == [
        "router", "cache", "retriever", "validator"
    ]
    critics = [n for n in ends if n["node"] == "critic"]
    assert [c["attempt"] for c in critics] == [0, 1]
    assert critics[0]["data"]["passed"] is False and critics[0]["data"]["retry_requested"] is True
    assert any("20%" in f for f in critics[0]["data"]["flagged_claims"])
    assert critics[1]["data"]["passed"] is True

    router = ends[0]["data"]
    assert router["tier"] == "70b" and router["card_kind"] == "invoice_audit"

    retrieved = {c["chunk_id"]: c for c in next(n for n in ends if n["node"] == "retriever")["data"]["chunks"]}
    assert {"vendor_sla_northwind_cloud", "invoice_policy_and_credits"} <= {c["doc_id"] for c in retrieved.values()}

    card = by_type(ev, "card")[0]["card"]
    findings_sum = sum(Decimal(str(f["discrepancy_usd"])) for f in card["findings"])
    assert card["kind"] == "invoice_audit" and card["verdict"] == "overbilled"
    assert Decimal(str(card["total_discrepancy_usd"])) == findings_sum == Decimal(9600)
    assert set(card["citations"]) <= set(retrieved)
    assert json.loads(by_type(ev, "card")[0]["raw_json"])["invoice_id"] == "INV-2291"

    triad = by_type(ev, "eval")[0]
    assert triad["schema_validity"] == 1.0 and triad["faithfulness"] >= 0.9 and triad["context_recall"] == 1.0
    assert done(ev)["hallucination_prevented"] is True and done(ev)["cache_hit"] is False
    assert ev[-1][0] == "done"


def test_hallucination_trap_naive_is_confidently_wrong(run_race):
    p = PRESETS["hallucination_trap"]
    ev = run_race("naive", p.query, p.id)
    text = "".join(d["text"] for d in by_type(ev, "token"))
    assert "45,600 is accurate" in text
    a = by_type(ev, "naive_analysis")[0]
    assert len(a["ungrounded_claims"]) >= 3 and a["schema_valid"] is False
    for c in a["ungrounded_claims"]:
        s, e = c["span"]
        assert 0 <= s < e <= len(text) and c["reason"]
    assert done(ev)["hallucination_prevented"] is False
    assert [e for e, _ in ev][:1] == ["meta"] and ev[-1][0] == "done"


def test_semantic_cache_paraphrase_hits_for_free(run_race):
    p = PRESETS["semantic_cache"]
    sid = "cache-race"
    first = run_race("engineered", p.query, p.id, session_id=sid)
    second = run_race("engineered", p.paraphrase, p.id, session_id=sid, variant="paraphrase")

    c1 = next(n for n in node_ends(first) if n["node"] == "cache")["data"]
    c2 = next(n for n in node_ends(second) if n["node"] == "cache")["data"]
    assert c1["hit"] is False
    assert c2["hit"] is True and c2["similarity"] >= 0.92 and c2["backend"] == "memory"

    skipped = [n["node"] for n in node_ends(second) if n["status"] == "skipped"]
    assert skipped == ["retriever", "generator", "critic"]
    d1, d2 = done(first), done(second)
    assert d2["cache_hit"] is True and d2["usage"]["cost_usd"] == 0.0 and d2["usage"]["prompt_tokens"] == 0
    assert d2["total_ms"] < 250  # real embedding + lookup; typically ~10-20 ms
    assert d1["usage"]["cost_usd"] > 0
    assert by_type(second, "card")[0]["card"] == by_type(first, "card")[0]["card"]
    assert by_type(second, "eval")[0]["schema_validity"] == 1.0
    assert not by_type(second, "token")


def test_naive_pays_full_price_for_the_repeat(run_race):
    p = PRESETS["semantic_cache"]
    costs = [done(run_race("naive", q, p.id))["usage"]["cost_usd"] for q in (p.query, p.paraphrase)]
    assert all(c > 0 for c in costs)


def test_cache_is_isolated_per_session(run_race):
    p = PRESETS["semantic_cache"]
    run_race("engineered", p.query, p.id, session_id="visitor-a")
    other = run_race("engineered", p.query, p.id, session_id="visitor-b")
    assert done(other)["cache_hit"] is False


def test_unrelated_query_does_not_hit_the_cache(run_race):
    p = PRESETS["semantic_cache"]
    run_race("engineered", p.query, p.id, session_id="miss-test")
    ev = run_race("engineered", "How many consecutive days may an employee be scheduled?", None, session_id="miss-test")
    assert done(ev)["cache_hit"] is False


def test_simple_triage_routes_to_the_cheap_tier(run_race):
    p = PRESETS["tier1_triage"]
    eng = run_race("engineered", p.query, p.id, model_mode="auto")  # default model_mode=70b forces parity
    naive = run_race("naive", p.query, p.id, model_mode="auto")
    router = node_ends(eng)[0]["data"]
    assert router["tier"] == "8b" and router["model"] == "llama-3.1-8b-instant"
    assert router["complexity_score"] < 0.5 and router["card_kind"] == "triage"

    card = by_type(eng, "card")[0]["card"]
    assert (card["category"], card["priority"], card["suggested_queue"]) == ("access", "P3", "IT-ACCESS")
    assert done(eng)["usage"]["tier"] == "8b" and done(naive)["usage"]["tier"] == "70b"
    assert done(eng)["usage"]["cost_usd"] < done(naive)["usage"]["cost_usd"] / 2
    assert by_type(naive, "naive_analysis")[0]["schema_valid"] is False


def test_prompt_injection_is_neutralised_and_schema_enforced(run_race):
    p = PRESETS["prompt_injection"]
    eng, naive = run_race("engineered", p.query, p.id), run_race("naive", p.query, p.id)

    router = node_ends(eng)[0]["data"]
    assert router["injection_detected"] is True and router["card_kind"] == "secure_response"
    assert "pwned" not in router["sanitized_query"].lower()

    card = by_type(eng, "card")[0]["card"]
    assert card["kind"] == "secure_response" and card["injection_blocked"] is True
    assert "$350" in card["answer"] and "PWNED" not in card["answer"]
    assert by_type(eng, "eval")[0]["schema_validity"] == 1.0

    text = "".join(d["text"] for d in by_type(naive, "token"))
    assert "PWNED" in text
    a = by_type(naive, "naive_analysis")[0]
    assert a["schema_valid"] is False and len(a["ungrounded_claims"]) >= 2


def test_custom_query_works_without_a_preset(run_race):
    ev = run_race("engineered", "How long is each on-call rotation and when does it hand over?")
    card = by_type(ev, "card")[0]["card"]
    assert card["kind"] == "faq" and "Monday" in card["answer"]
    assert by_type(ev, "eval")[0]["context_recall"] is None
    assert ev[-1][0] == "done"


def test_router_derives_card_kind_without_preset_hints(run_race):
    for pid, kind in [("hallucination_trap", "invoice_audit"), ("semantic_cache", "faq"),
                      ("tier1_triage", "triage"), ("prompt_injection", "secure_response")]:
        ev = run_race("engineered", PRESETS[pid].query, None)  # no preset_id supplied
        assert node_ends(ev)[0]["data"]["card_kind"] == kind


# --- v2: every domain's three presets, both sides, through the SSE API ---------------------------------------------
from app import domains as dom  # noqa: E402

DOMAIN_IDS = ["travel_appr", "bc_tenancy_cra", "nutrition", "b2b_sla"]
HERO_KIND = {"travel_appr": "appr_claim", "bc_tenancy_cra": "tenancy_tax", "nutrition": "nutrition_audit",
             "b2b_sla": "invoice_audit"}


def _preset(domain, kind):
    return next(p for p in dom.get_domain(domain).presets if p.kind == kind)


def _text(ev):
    return "".join(d["text"] for d in by_type(ev, "token"))


@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_hero_engineered_returns_the_correct_card_and_verdict(run_race, domain):
    p = _preset(domain, "hallucination_trap")
    ev = run_race("engineered", p.query, p.id, domain=domain, session_id=f"hero-e-{domain}")
    card = by_type(ev, "card")[0]["card"]
    assert card["kind"] == HERO_KIND[domain] == p.card_kind
    v = by_type(ev, "verdict")[0]
    assert v["key_applies"] is True and v["forbidden_hits"] == []
    assert all(r["found"] for r in v["required"]), v
    assert v["correct"] is True
    critics = [n for n in node_ends(ev) if n["node"] == "critic"]
    assert critics[-1]["data"]["passed"] is True, critics[-1]["data"]["flagged_claims"]
    assert by_type(ev, "eval")[0]["schema_validity"] == 1.0
    assert done(ev)["usage"]["source"] == "estimate" and done(ev)["mode"] == "demo" and done(ev)["degraded"] is False
    assert by_type(ev, "meta")[0]["domain"] == domain


@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_hero_naive_falls_for_the_trap(run_race, domain):
    p = _preset(domain, "hallucination_trap")
    ev = run_race("naive", p.query, p.id, domain=domain, session_id=f"hero-n-{domain}")
    text = _text(ev)
    v = by_type(ev, "verdict")[0]
    assert v["key_applies"] is True and v["correct"] is False and v["forbidden_hits"], v
    a = by_type(ev, "naive_analysis")[0]
    assert a["schema_valid"] is False and a["ungrounded_claims"]
    for c in a["ungrounded_claims"]:
        s, e = c["span"]
        assert 0 <= s < e <= len(text) and c["reason"]  # spans index into the FINAL streamed text
    for h in v["forbidden_hits"]:
        s, e = h["span"]
        assert 0 <= s < e <= len(text)


@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_tier1_router_picks_cheap_model_and_answers_in_one_card(run_race, domain):
    p = _preset(domain, "tier1_router")
    ev = run_race("engineered", p.query, p.id, domain=domain, model_mode="auto", session_id=f"t1-{domain}")
    router = node_ends(ev)[0]["data"]
    assert router["tier"] == "8b" and router["card_kind"] == p.card_kind, router["reason"]
    assert by_type(ev, "card")[0]["card"]["kind"] == p.card_kind
    v = by_type(ev, "verdict")[0]
    assert v["key_applies"] is True and v["correct"] is True, v


@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_injection_is_blocked_on_engineered_and_obeyed_on_naive(run_race, domain):
    p = _preset(domain, "prompt_injection")
    eng = run_race("engineered", p.query, p.id, domain=domain, session_id=f"inj-e-{domain}")
    assert node_ends(eng)[0]["data"]["injection_detected"] is True
    card = by_type(eng, "card")[0]["card"]
    assert card["kind"] == "secure_response" and card["injection_blocked"] is True
    assert by_type(eng, "verdict")[0]["forbidden_hits"] == []
    naive = run_race("naive", p.query, p.id, domain=domain, session_id=f"inj-n-{domain}")
    nv = by_type(naive, "verdict")[0]
    assert nv["correct"] is False and nv["forbidden_hits"], nv
    assert by_type(naive, "naive_analysis")[0]["ungrounded_claims"]


@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_edited_hero_prompt_drops_the_key_but_still_runs(run_race, domain):
    p = _preset(domain, "hallucination_trap")
    edited = p.query.replace("6.5", "7.5").replace("6%", "5%").replace("Habanero Jack", "Pepper Jack").replace("99.62%", "99.8%")
    ev = run_race("engineered", edited, None, domain=domain, session_id=f"edit-{domain}")
    assert done(ev)["mode"] == "demo" and ev[-1][0] == "done"
    assert by_type(ev, "verdict")  # always emitted, key_applies reports whether the key could be recomputed


def test_model_mode_8b_gives_both_sides_the_same_model(run_race):
    p = _preset("travel_appr", "hallucination_trap")
    n = run_race("naive", p.query, p.id, domain="travel_appr", model_mode="8b", session_id="par-n")
    e = run_race("engineered", p.query, p.id, domain="travel_appr", model_mode="8b", session_id="par-e")
    assert by_type(n, "meta")[0]["model"] == by_type(e, "meta")[0]["model"] == "llama-3.1-8b-instant"
    assert done(n)["usage"]["tier"] == done(e)["usage"]["tier"] == "8b"
    assert node_ends(e)[0]["data"]["tier"] == "8b"
    assert by_type(e, "payload")[0]["model"] == by_type(n, "payload")[0]["model"] == "llama-3.1-8b-instant"
    # naive full_kb dwarfs the engineered payload: that is the point of the demo
    assert by_type(n, "payload")[0]["token_count"] > by_type(e, "payload")[0]["token_count"]
