"""Naive baseline: raw prompt (+ optionally the whole KB) -> heavy LLM -> unstructured text, plus post-hoc analysis.

The failure analysis is deterministic and runs on the FINAL streamed text (after any Reset): answer-key
forbidden-pattern spans + a sentence-level numeric grounding check against the retrieved ground truth.
"""
import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from pydantic import ValidationError

from app.deps import AppContext
from app.eval.grounding import evaluate_grounding
from app.llm.base import LLMRequest
from app.llm.gateway import RaceRun
from app.pipeline.setup import RaceSetup, make_setup, verdict_dict
from app.pipeline.streaming import EventPump, stream_tokens
from app.presets import PRESETS
from app.schemas import CARD_MODELS, RaceRequest, RetrievedChunk
from app.sse import Emitter

_SENT = re.compile(r"[^.!?\n]+[.!?]?")
_QUOTED = re.compile(r"[\"“]([^\"”]{3,80})[\"”]")
_FORCED = re.compile(
    r"\b(?:say|state|claim|reply|respond|answer)\b(?: only)?(?: with)?(?: that)? ([^.,;!?\"]{8,70})", re.I
)


def injection_spans(query: str, text: str) -> list[tuple[list[int], str]]:
    """Where the naive answer OBEYED an injected instruction in the query: it repeats the forced output or talks
    about its system prompt. Deterministic string matching, only active when the query itself looks injected."""
    from app.pipeline.guardrails import scan

    if not scan(query)[0]:
        return []
    out: list[tuple[list[int], str]] = []
    forced = [m.group(1).strip() for m in _QUOTED.finditer(query)]
    forced += [
        m.group(1).strip() for m in _FORCED.finditer(query) if not re.search(r"system prompt|instructions", m.group(1), re.I)
    ]
    for phrase in forced:
        for m in re.finditer(re.escape(phrase), text, re.I):
            out.append(([m.start(), m.end()], "Obeys the injected instruction (repeats the forced output)"))
    if re.search(r"system prompt", query, re.I):
        for m in re.finditer(r"system prompt", text, re.I):
            out.append(([m.start(), m.end()], "Discusses or leaks its system prompt"))
    return out


def legacy_marker_spans(preset_id: str | None, text: str) -> list[tuple[list[int], str]]:
    """Secondary signal for the original B2B presets: hand-written regexes tuned to known wrong claims."""
    legacy = PRESETS.get(preset_id or "")
    if not legacy:
        return []
    return [
        ([m.start(), m.end()], reason)
        for pattern, reason in legacy.wrong_markers
        for m in re.finditer(pattern, text, flags=re.I)
    ]


def _dedupe(spans: list[tuple[list[int], str]]) -> list[tuple[list[int], str]]:
    kept: list[tuple[list[int], str]] = []
    for span, reason in sorted((x for x in spans if x[0]), key=lambda x: (x[0][0], -(x[0][1] - x[0][0]))):
        if kept and span[0] < kept[-1][0][1]:
            continue
        kept.append((span, reason))
    return kept


def analyze_naive(
    text: str, card_kind: str, truth: list[RetrievedChunk], query: str, forbidden_spans: list[tuple[list[int], str]] = ()
) -> dict[str, Any]:
    """Check the naive output against ground truth. Never trusts that it is wrong: every flag has a reason."""
    claims: list[dict[str, Any]] = [{"span": list(span), "reason": reason} for span, reason in forbidden_spans if span]
    context = "\n".join(c.text for c in truth)
    for m in _SENT.finditer(text):
        sentence = m.group(0)
        if not sentence.strip() or any(c["span"][0] < m.end() and m.start() < c["span"][1] for c in claims):
            continue
        g = evaluate_grounding(sentence, context, query)
        # Only numeric claims are judged at sentence level (prose overlap is too noisy for the left panel).
        numeric = [u for u in g.unsupported if "cannot be derived" in u or "is not stated" in u]
        if numeric:
            claims.append({"span": [m.start(), m.end()], "reason": numeric[0]})
    claims.sort(key=lambda c: c["span"][0])

    schema_errors: list[str] = []
    try:
        payload = json.loads(text)
        CARD_MODELS[card_kind].model_validate(payload)
    except json.JSONDecodeError:
        schema_errors.append("Output is free-form text, not JSON")
    except ValidationError as e:
        schema_errors.extend(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()[:5])
    return {"ungrounded_claims": claims, "schema_valid": not schema_errors, "schema_errors": schema_errors}


def meta_fields(setup: RaceSetup, model_label: str) -> dict[str, Any]:
    run, req = setup.run, setup.req
    return dict(
        mode=run.mode, query=req.query, preset_id=req.preset_id, model=model_label,
        fallback_reason=setup.fallback_reason(), race_id=req.race_id, domain=req.domain, provider=run.provider,
        base_model=setup.base_model(), model_mode=req.model_mode, context_mode=req.context_mode,
        kb_tokens=setup.kb_tokens,
    )


async def run_naive(
    ctx: AppContext, req: RaceRequest, em: Emitter, run: RaceRun | None = None
) -> AsyncIterator[dict[str, Any]]:
    run = run or ctx.llm.run_for(req.race_id, "anon", req.force_demo)
    setup = make_setup(ctx, req, run)
    tier = setup.naive_tier()
    yield em.event("meta", **meta_fields(setup, setup.model_for(tier)))
    yield em.event("race_state", degraded=run.degraded, reason=run.degraded_reason, provider=run.provider)
    if run.degraded:
        run.take_notification("naive")

    pump = EventPump(em)
    llm_req = LLMRequest(
        role="naive", tier=tier, query=req.query, preset_id=req.preset_id, domain=req.domain,
        preset_kind=setup.preset_kind, context_mode=req.context_mode, kb_text=setup.runtime.spec.kb_text,
    )
    async for event in pump.run(stream_tokens(ctx, run, llm_req, pump.emit)):
        yield event
    text, usage, fallback_reason = pump.result
    total_ms = em.ms()  # the race clock stops when the answer finishes, before post-hoc analysis

    truth = [
        RetrievedChunk(
            chunk_id=h.chunk.chunk_id, doc_id=h.chunk.doc_id, doc_title=h.chunk.doc_title,
            section=h.chunk.section, text=h.chunk.text, rrf_score=h.rrf_score, rank=h.rank,
        )
        for h in await asyncio.to_thread(setup.runtime.retriever.retrieve, req.query, 4)
    ]
    verdict = verdict_dict(text, setup.expected)
    # Primary signal: answer-key forbidden hits. Secondary: injection obedience, legacy B2B markers.
    forbidden = _dedupe(
        [(h["span"], h["label"]) for h in verdict["forbidden_hits"]]
        + injection_spans(req.query, text)
        + legacy_marker_spans(req.preset_id if req.domain == "b2b_sla" else None, text)
    )
    kind = setup.preset.card_kind if setup.preset else "faq"
    analysis = analyze_naive(text, kind, truth, req.query, forbidden)
    yield em.event("naive_analysis", **analysis)
    if not verdict["key_applies"]:
        # No answer key for an edited prompt: fall back to "no unsupported numeric claim".
        verdict["correct"] = not analysis["ungrounded_claims"]
    yield em.event("verdict", **verdict)
    if run.degraded and run.take_notification("naive"):  # the sibling gave up after this side finished
        yield em.event("race_state", degraded=True, reason=run.degraded_reason, provider=run.provider)
    live = run.mode == "live" and not run.degraded and not fallback_reason
    yield em.event(
        "done", total_ms=total_ms, usage=usage.model_dump(), cache_hit=False, hallucination_prevented=False,
        mode="live" if live else "demo", degraded=run.degraded,
    )
