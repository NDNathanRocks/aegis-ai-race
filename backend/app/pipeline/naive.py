"""Naive baseline: Raw Prompt -> heavy 70B LLM -> unstructured text, plus post-hoc failure analysis."""
import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from pydantic import ValidationError

from app.deps import AppContext
from app.eval.grounding import evaluate_grounding
from app.llm.base import LLMRequest
from app.pipeline.streaming import EventPump, stream_tokens
from app.presets import Preset, get_preset
from app.schemas import CARD_MODELS, RaceRequest, RetrievedChunk
from app.sse import Emitter

_SENT = re.compile(r"[^.!?\n]+[.!?]?")


def analyze_naive(text: str, preset: Preset | None, truth: list[RetrievedChunk], query: str) -> dict[str, Any]:
    """Check the naive output against ground truth. Never trusts that it is wrong: every flag has a reason."""
    claims: list[dict[str, Any]] = []
    if preset:
        for pattern, reason in preset.wrong_markers:
            for m in re.finditer(pattern, text, flags=re.I):
                claims.append({"span": [m.start(), m.end()], "reason": reason})
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

    kind = preset.card_kind if preset else "faq"
    schema_errors: list[str] = []
    try:
        payload = json.loads(text)
        CARD_MODELS[kind].model_validate(payload)
    except json.JSONDecodeError:
        schema_errors.append("Output is free-form text, not JSON")
    except ValidationError as e:
        schema_errors.extend(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()[:5])
    return {"ungrounded_claims": claims, "schema_valid": not schema_errors, "schema_errors": schema_errors}


async def run_naive(ctx: AppContext, req: RaceRequest, em: Emitter) -> AsyncIterator[dict[str, Any]]:
    mode, reason = ctx.llm.mode(req.force_demo)
    yield em.event(
        "meta", mode=mode, query=req.query, preset_id=req.preset_id,
        model=ctx.settings.groq_heavy_model, fallback_reason=reason,
    )
    pump = EventPump(em)
    llm_req = LLMRequest(role="naive", tier="70b", query=req.query, preset_id=req.preset_id)
    async for event in pump.run(stream_tokens(ctx, llm_req, pump.emit, force_demo=req.force_demo)):
        yield event
    text, usage, fallback_reason = pump.result
    total_ms = em.ms()  # the race clock stops when the answer finishes, before post-hoc analysis

    truth = [
        RetrievedChunk(
            chunk_id=h.chunk.chunk_id, doc_id=h.chunk.doc_id, doc_title=h.chunk.doc_title,
            section=h.chunk.section, text=h.chunk.text, rrf_score=h.rrf_score, rank=h.rank,
        )
        for h in await asyncio.to_thread(ctx.retriever.retrieve, req.query, 4)
    ]
    yield em.event("naive_analysis", **analyze_naive(text, get_preset(req.preset_id), truth, req.query))
    yield em.event(
        "done", total_ms=total_ms, usage=usage.model_dump(), cache_hit=False, hallucination_prevented=False,
        mode="demo" if fallback_reason else mode,
    )
