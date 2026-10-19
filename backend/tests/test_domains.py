import json
import re
from pathlib import Path

import pytest

from app import domains as dom
from app.domains import DOMAIN_ORDER

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "contract-v2.md"
CORPUS = ROOT / "backend" / "data" / "corpus"


def _contract_lines():
    return CONTRACT.read_text(encoding="utf-8").splitlines()


def _hero(tag):
    lines = _contract_lines()
    for i, ln in enumerate(lines):
        if ln.startswith(f"**{tag} / hero"):
            return next(m[2:].strip() for m in lines[i + 1 :] if m.startswith("> "))
    raise KeyError(tag)


def _bullet(section, key):
    on = False
    for ln in _contract_lines():
        if ln.startswith(f"**{section}"):
            on = True
        elif on and ln.startswith(f"- {key}:"):
            return re.search(r"`(.*)`", ln).group(1)
    raise KeyError((section, key))


def _facts_hit(facts, blob):
    return [f for f in facts if not any(a.strip() in blob for a in f.split(" || "))]


def test_registry_basics():
    assert [d.id for d in dom.list_domains()] == list(DOMAIN_ORDER)
    with pytest.raises(KeyError):
        dom.get_domain("../etc")
    assert dom.get_preset("b2b_sla", "nope") is None
    assert dom.get_preset("nope", "hallucination_trap") is None
    for d in dom.list_domains():
        assert [p.kind for p in d.presets] == ["hallucination_trap", "tier1_router", "prompt_injection"]
        assert d.presets[0].paraphrase
        assert dom.get_preset(d.id, d.presets[0].id) is d.presets[0]


@pytest.mark.parametrize("domain", DOMAIN_ORDER)
def test_kb_token_budget(domain):
    spec = dom.get_domain(domain)
    assert 2500 <= spec.kb_tokens <= 3500, spec.kb_tokens  # ~4 chars/token estimate
    assert spec.kb_tokens == dom.estimate_tokens(spec.kb_text)


def test_legacy_b2b_ids_and_semantic_cache_alias():
    ids = [p.id for p in dom.get_domain("b2b_sla").presets]
    assert ids == ["hallucination_trap", "tier1_triage", "prompt_injection"]
    alias = dom.get_preset("b2b_sla", "semantic_cache")
    assert alias and alias.query == dom.get_domain("b2b_sla").presets[0].paraphrase


@pytest.mark.skipif(not CONTRACT.exists(), reason="contract doc not present")
def test_verbatim_prompts_equal_contract_section_3():
    expect = {
        ("travel_appr", 0): _hero("travel_appr"),
        ("bc_tenancy_cra", 0): _hero("bc_tenancy_cra"),
        ("nutrition", 0): _hero("nutrition"),
        ("travel_appr", 1): _bullet("Tier-1 router", "travel"),
        ("bc_tenancy_cra", 1): _bullet("Tier-1 router", "tenancy"),
        ("nutrition", 1): _bullet("Tier-1 router", "nutrition"),
        ("travel_appr", 2): _bullet("Prompt injection", "travel"),
        ("bc_tenancy_cra", 2): _bullet("Prompt injection", "tenancy"),
        ("nutrition", 2): _bullet("Prompt injection", "nutrition"),
    }
    for (d, i), text in expect.items():
        assert dom.get_domain(d).presets[i].query == text, (d, i)
    b2b = dom.get_domain("b2b_sla").presets
    assert b2b[0].query == _hero("b2b_sla")
    from app.presets import PRESETS  # legacy B2B prompts are unchanged

    assert b2b[1].query == PRESETS["tier1_triage"].query
    assert b2b[2].query == PRESETS["prompt_injection"].query


def test_domain_json_matches_loaded_specs():
    for d in dom.list_domains():
        raw = json.loads((CORPUS / d.id / "domain.json").read_text(encoding="utf-8"))
        assert raw["id"] == d.id and raw["answer_key"] == d.answer_key
        assert {k for k in raw["answer_key"]} == {"hallucination_trap", "tier1_router", "prompt_injection"}


@pytest.mark.parametrize("domain", DOMAIN_ORDER)
def test_every_preset_query_is_a_known_text_for_hashing_retriever(domain, settings, embedder):
    """Plumbing only (hashing embedder): build_domains runs, warms and serves cached hits."""
    rt = dom.build_domains(settings, embedder, warm=False)[domain]
    stats = rt.warm()
    assert stats["queries"] >= 3
    q = rt.spec.presets[0].query
    first = rt.retriever.retrieve(q, 4, 10, "hybrid", None, True)
    assert rt.retriever.retrieve(q, 4, 10, "hybrid", None, True) == first


# --- real model -------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def real_runtimes(settings):
    from tests.conftest import REAL_EMBEDDER

    return dom.build_domains(settings, REAL_EMBEDDER, warm=False), REAL_EMBEDDER


@pytest.mark.model
@pytest.mark.parametrize("domain", DOMAIN_ORDER)
def test_hero_context_recall_is_1_at_k4(real_runtimes, domain):
    runtimes, _ = real_runtimes
    rt = runtimes[domain]
    raw = json.loads((CORPUS / domain / "domain.json").read_text(encoding="utf-8"))
    facts = raw["retrieval_facts"]["hallucination_trap"]
    for q in (rt.spec.presets[0].query, rt.spec.presets[0].paraphrase):
        blob = "\n".join(h.chunk.text for h in rt.retriever.retrieve(q, 4, 10, "hybrid", None, True))
        assert not _facts_hit(facts, blob), _facts_hit(facts, blob)


@pytest.mark.model
@pytest.mark.parametrize("domain", DOMAIN_ORDER)
def test_tier1_router_recall_at_k2(real_runtimes, domain):
    """The 8B path retrieves only 2 chunks: every Tier-1 lookup must still find its fact chunk."""
    runtimes, _ = real_runtimes
    rt = runtimes[domain]
    raw = json.loads((CORPUS / domain / "domain.json").read_text(encoding="utf-8"))
    facts = raw["retrieval_facts"]["tier1_router"]
    q = rt.spec.presets[1].query
    for decompose in (True, False):
        blob = "\n".join(h.chunk.text for h in rt.retriever.retrieve(q, 2, 10, "hybrid", None, decompose))
        assert not _facts_hit(facts, blob), (decompose, _facts_hit(facts, blob))


@pytest.mark.model
@pytest.mark.parametrize("domain", DOMAIN_ORDER)
def test_hero_paraphrase_cosine_at_least_0_92(real_runtimes, domain):
    _, emb = real_runtimes
    p = dom.get_domain(domain).presets[0]
    a, b = emb.embed([p.query, p.paraphrase])
    assert float(a @ b) >= 0.92


@pytest.mark.model
def test_warmed_preset_retrieval_is_fast(real_runtimes):
    import time

    runtimes, emb = real_runtimes
    dom.warm_domains(runtimes, emb)
    times = []
    for rt in runtimes.values():
        for p in rt.spec.presets:
            for q in (p.query, p.paraphrase):
                if not q:
                    continue
                t = time.perf_counter()
                rt.retriever.retrieve(q, 4, 10, "hybrid", None, True)
                emb.embed([q])
                times.append((time.perf_counter() - t) * 1000)
    assert sorted(times)[int(0.95 * (len(times) - 1))] < 50
