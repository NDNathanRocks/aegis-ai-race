"""Domain registry: per-domain knowledge base, presets, answer keys, calculators and retrieval runtimes.

Public interface is frozen in docs/contract-v2.md section 4:
    get_domain, list_domains, get_preset, expected_answer, check_answer, DomainRuntime, build_domains
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import appr, invoice, nutrition, tenancy_tax
from .answer import check_answer
from .types import ExpectedAnswer, ForbiddenPattern, PresetSpec, RequiredValue, VerdictResult

__all__ = [
    "DomainSpec", "DomainRuntime", "PresetSpec", "ExpectedAnswer", "RequiredValue", "ForbiddenPattern",
    "VerdictResult", "get_domain", "list_domains", "get_preset", "expected_answer", "check_answer",
    "build_domains", "warm_domains", "estimate_tokens",
]

log = logging.getLogger("aegis.domains")

DOMAIN_ORDER = ("travel_appr", "bc_tenancy_cra", "nutrition", "b2b_sla")
CALCULATORS = {
    "appr": appr.expected,
    "tenancy_tax": tenancy_tax.expected,
    "nutrition": nutrition.expected,
    "invoice": invoice.expected,
}


def estimate_tokens(text: str) -> int:
    """tiktoken-free estimate (~4 characters per token); labelled an estimate wherever shown."""
    return max(1, round(len(text) / 4))


@dataclass(frozen=True)
class DomainSpec:
    id: str
    title: str
    emoji: str
    blurb: str
    presets: tuple[PresetSpec, ...]
    answer_key: dict
    kb_text: str
    kb_tokens: int


@dataclass
class DomainRuntime:
    spec: DomainSpec
    chunks: list
    retriever: Any
    warm_stats: dict = field(default_factory=dict)

    def warm(self) -> dict:
        """Pre-populate the query-vector and hits caches for every preset query and paraphrase."""
        self.warm_stats = _warm_one(self)
        return self.warm_stats


def _corpus_root() -> Path:
    from app.config import BACKEND_DIR

    return BACKEND_DIR / "data" / "corpus"


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q).strip()


@lru_cache(maxsize=8)
def _load(domain_id: str, root: str) -> DomainSpec:
    from app.rag.corpus import load_documents

    d = Path(root) / domain_id
    meta = json.loads((d / "domain.json").read_text(encoding="utf-8"))
    presets = tuple(PresetSpec(**p) for p in meta["presets"])
    kb_text = "\n\n".join(doc.text.strip() for doc in load_documents(d))
    return DomainSpec(
        id=meta["id"], title=meta["title"], emoji=meta["emoji"], blurb=meta["blurb"], presets=presets,
        answer_key=meta.get("answer_key", {}), kb_text=kb_text, kb_tokens=estimate_tokens(kb_text),
    )


def get_domain(domain_id: str, corpus_root: Path | None = None) -> DomainSpec:
    """Raises KeyError for an unknown domain id (ids are an allowlist, never a path)."""
    if domain_id not in DOMAIN_ORDER:
        raise KeyError(domain_id)
    return _load(domain_id, str(corpus_root or _corpus_root()))


def list_domains(corpus_root: Path | None = None) -> list[DomainSpec]:
    return [get_domain(d, corpus_root) for d in DOMAIN_ORDER]


def get_preset(domain_id: str, preset_id: str | None) -> PresetSpec | None:
    """None if unknown. Legacy B2B ids are the real ids; `semantic_cache` is an alias of the B2B hero paraphrase."""
    if not preset_id:
        return None
    try:
        spec = get_domain(domain_id)
    except KeyError:
        return None
    for p in spec.presets:
        if p.id == preset_id:
            return p
    if domain_id == "b2b_sla" and preset_id == "semantic_cache":
        hero = next(p for p in spec.presets if p.kind == "hallucination_trap")
        return PresetSpec(
            id="semantic_cache", kind="hallucination_trap", title="The Semantic Cache Race",
            tagline="Paraphrased Repeat", query=hero.paraphrase or hero.query, paraphrase=None,
            card_kind=hero.card_kind,
        )
    return None


def expected_answer(domain_id: str, preset_kind: str, query: str) -> ExpectedAnswer | None:
    """Answer key for `query`, recomputed from the prompt's own numbers. None = the key does not apply.

    Calculator keys re-derive the figures from the (possibly edited) prompt; "static" keys apply only while the
    prompt is still a preset's query or paraphrase."""
    try:
        spec = get_domain(domain_id)
    except KeyError:
        return None
    key = spec.answer_key.get(preset_kind)
    if not key:
        return None
    calc = key.get("calculator")
    if calc == "static":
        qn = _norm(query)
        kind_presets = [p for p in spec.presets if p.kind == preset_kind]
        if not any(qn in (_norm(p.query), _norm(p.paraphrase or "")) for p in kind_presets):
            return None
        return ExpectedAnswer(
            "static",
            tuple(RequiredValue(r["label"], r["value"], r.get("unit", "")) for r in key.get("required", [])),
            tuple(ForbiddenPattern(f["label"], f["pattern"]) for f in key.get("forbidden", [])),
        )
    fn = CALCULATORS.get(calc)
    if fn is None:
        return None
    qn = _norm(query)
    for p in spec.presets:  # a preset's own paraphrase is the same scenario: score it with the canonical wording
        if p.kind == preset_kind and p.paraphrase and qn == _norm(p.paraphrase):
            query = p.query
            break
    return fn(query, key)


# --- retrieval runtimes -------------------------------------------------------------------------------------------
# One retriever per (k, decompose) combination the pipeline actually uses: naive k=4 plain, engineered k=4/2 decomposed.
_WARM_SHAPES = ((4, False), (4, True), (2, True))


def _warm_texts(spec: DomainSpec) -> list[str]:
    texts: list[str] = []
    for p in spec.presets:
        for q in (p.query, p.paraphrase):
            if not q:
                continue
            texts.append(q)
            try:  # the router retrieves with the injection-sanitized text
                from app.pipeline.guardrails import scan

                _, sanitized = scan(q)
                if sanitized and sanitized != q:
                    texts.append(sanitized)
            except Exception:  # pragma: no cover - guardrails belong to another module; never block warm-up
                pass
    return list(dict.fromkeys(texts))


def _warm_one(rt: DomainRuntime) -> dict:
    t0 = time.perf_counter()
    texts = _warm_texts(rt.spec)
    for q in texts:
        for k, decompose in _WARM_SHAPES:
            rt.retriever.retrieve(q, k, 10, "hybrid", None, decompose)
    return {"queries": len(texts), "ms": round((time.perf_counter() - t0) * 1000, 1)}


def warm_domains(runtimes: dict[str, DomainRuntime], embedder=None) -> dict[str, dict]:
    """Realistic-length warm-up of the ONNX session, then per-domain cache pre-population.

    Run in a worker thread at startup; `/api/health` should report ready only after this returns."""
    if embedder is not None:
        sample = " ".join(p.query for rt in runtimes.values() for p in rt.spec.presets[:1])
        embedder.embed([sample[:600], sample[:200], "short probe"])
    return {did: rt.warm() for did, rt in runtimes.items()}


def build_domains(settings, embedder, *, warm: bool = True, on_warm=None) -> dict[str, DomainRuntime]:
    """One chunk list + vector index + retriever per domain. Called in lifespan (in a worker thread).

    With warm=True (default) the caches are populated before returning; pass warm=False and call
    `warm_domains(runtimes, embedder)` later to flip a readiness flag yourself. `on_warm(stats)` is a completion hook."""
    from app.rag.corpus import load_chunks
    from app.rag.hybrid import build_retriever

    root = Path(settings.corpus_dir)
    runtimes: dict[str, DomainRuntime] = {}
    for did in DOMAIN_ORDER:
        spec = get_domain(did, root)
        chunks = load_chunks(root / did)
        runtimes[did] = DomainRuntime(spec, chunks, build_retriever(settings, embedder, chunks, namespace=did))
    if warm:
        stats = warm_domains(runtimes, embedder)
        log.info("domains warm: %s", stats)
        if on_warm:
            on_warm(stats)
    return runtimes
