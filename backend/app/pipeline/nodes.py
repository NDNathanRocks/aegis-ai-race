"""The six stages of the engineered pipeline, as LangGraph node functions.

    Router -> SemanticCache -> HybridRetriever -> Generator -> HallucinationCritic -> PydanticValidator
"""
import asyncio
import json
import re
import time
from typing import Any, TypedDict

import numpy as np
from pydantic import ValidationError

from app.eval.grounding import evaluate_grounding
from app.eval.triad import score_triad
from app.llm import simulator
from app.llm.base import LLMRequest
from app.pipeline import guardrails
from app.pipeline.setup import RaceSetup, expected_text
from app.pipeline.streaming import Emit, stream_tokens
from app.schemas import (
    CARD_MODELS,
    CacheLookup,
    CriticVerdict,
    RetrievedChunk,
    RouterDecision,
    TriadScores,
)

MAX_RETRIES = 1
FAITHFULNESS_THRESHOLD = 0.7
TIER_THRESHOLD = 0.5

_SIMPLE = re.compile(r"\b(classif\w*|categori[sz]e|label|tag|format|reformat|priority|triage|reset|summari[sz]e)\b", re.I)
_REASONING = re.compile(
    r"\b(audit|compare|calculat\w*|discrepanc\w*|reconcil\w*|why|explain|analy[sz]e|verify|every|derive|show"
    r"|penalt\w*|payout|owed|violations?)\b",
    re.I,
)
_INVOICE = re.compile(r"\b(invoice|audit|billed|discrepanc\w*)\b", re.I)
_TRIAGE = re.compile(r"\b(classif\w*|triage|ticket|priority)\b", re.I)
_NUMBER = re.compile(r"\$?\d[\d,.]*%?")
# Per-domain computational card: chosen when the (sanitised) question is a number-heavy audit/claim.
_DOMAIN_CARD: dict[str, tuple[re.Pattern[str], str]] = {
    "travel_appr": (re.compile(r"\b(appr|compensat\w*|payout|refund\w*|delayed?|owed)\b", re.I), "appr_claim"),
    "bc_tenancy_cra": (re.compile(r"\b(rent|tfsa|cra|evict\w*|landlord|tenan\w*)\b", re.I), "tenancy_tax"),
    "nutrition": (re.compile(r"\b(audit|calculat\w*|totals?|footlong|sandwich|order|violations?)\b", re.I), "nutrition_audit"),
}
SPECIAL_KINDS = {"invoice_audit", "appr_claim", "tenancy_tax", "nutrition_audit"}


class State(TypedDict, total=False):
    sanitized: str
    query_vec: Any
    router: RouterDecision
    cache: CacheLookup
    chunks: list[RetrievedChunk]
    draft: str
    attempt: int
    feedback: list[str]
    critic: CriticVerdict
    grounding_flagged: bool
    faithfulness: float
    unsupported: list[str]
    card: dict[str, Any] | None
    schema_valid: bool
    prompt_tokens: int
    completion_tokens: int
    usage_sources: list[str]
    fallback_reason: str | None
    triad: TriadScores


def parse_json_object(text: str) -> Any:
    """Parse a JSON object from LLM output, tolerating code fences and surrounding prose."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise json.JSONDecodeError("no JSON object found", t, 0)
    return json.loads(t[start : end + 1])


def _validation_messages(e: ValidationError) -> list[str]:
    return [f"{'.'.join(map(str, err['loc'])) or 'card'}: {err['msg']}" for err in e.errors()[:6]]


class Nodes:
    def __init__(self, setup: RaceSetup, emit: Emit):
        self.setup, self.ctx, self.req, self.emit = setup, setup.ctx, setup.req, emit
        self.preset = setup.preset
        self.run = setup.run

    async def _stage(self, name: str, fn, **extra: Any) -> dict[str, Any]:
        await self.emit("node_start", node=name, **extra)
        t0 = time.perf_counter()
        update, data, status = await fn()
        await self.emit(
            "node_end", node=name, latency_ms=round((time.perf_counter() - t0) * 1000, 2), status=status, data=data, **extra
        )
        return update

    # ---- 1. Guardrail & Semantic Router --------------------------------------------------
    async def router(self, state: State) -> dict[str, Any]:
        async def work():
            ctx, s = self.ctx, self.ctx.settings
            patterns, sanitized = guardrails.scan(self.req.query)
            sanitized = sanitized or self.req.query
            qvec = (await asyncio.to_thread(ctx.embedder.embed, [sanitized]))[0]
            proto_c, proto_s = ctx.prototypes()

            words = len(sanitized.split())
            length = min(words / 80, 1.0) * 0.3
            keywords = min(len({m.lower() for m in _REASONING.findall(sanitized)}) * 0.2, 0.4)
            n_nums = len(_NUMBER.findall(sanitized))
            numeric = 0.2 if n_nums >= 4 else 0.1 if n_nums >= 2 else 0.0
            simple = -0.2 if _SIMPLE.search(sanitized) else 0.0
            semantic = float(np.clip(0.5 + 1.5 * (float((proto_c @ qvec).max()) - float((proto_s @ qvec).max())), 0, 1)) * 0.3
            score = float(np.clip(length + keywords + numeric + simple + semantic, 0, 1))
            would_pick = "70b" if score >= TIER_THRESHOLD else "8b"
            mode_ = self.req.model_mode
            tier = would_pick if mode_ == "auto" else mode_  # model parity: 70b / 8b force both sides to one model

            domain_rx, domain_kind = _DOMAIN_CARD.get(self.req.domain, (None, None))
            if patterns:
                kind = "secure_response"
            elif self.req.domain == "b2b_sla" and _INVOICE.search(sanitized) and n_nums >= 2:
                kind = "invoice_audit"
            elif domain_rx is not None and n_nums >= 2 and domain_rx.search(sanitized) and _REASONING.search(sanitized):
                kind = domain_kind
            elif self.req.domain == "b2b_sla" and _TRIAGE.search(sanitized):
                kind = "triage"
            else:
                kind = "faq"
            if (
                kind in SPECIAL_KINDS
                and self.run.provider == "simulator"
                and not simulator.can_build(kind, sanitized, self.req.preset_id, self.req.domain)
            ):
                kind = "faq"  # the demo simulator can only compute the hero scenarios; edited prompts get a FAQ card
            decision = RouterDecision(
                complexity_score=round(score, 3),
                tier=tier,
                model=s.groq_heavy_model if tier == "70b" else s.groq_fast_model,
                card_kind=kind,
                injection_detected=bool(patterns),
                injection_patterns=patterns,
                sanitized_query=sanitized,
                reason=(
                    f"length {length:.2f} + reasoning {keywords:.2f} + numeric {numeric:.2f} "
                    f"+ simple-task {simple:.2f} + semantic {semantic:.2f}"
                    + (f"; model_mode={mode_} forces {tier} (router alone would pick {would_pick})" if mode_ != "auto" else "")
                ),
            )
            update = {
                "sanitized": sanitized, "query_vec": qvec, "router": decision, "attempt": 0, "feedback": [],
                "prompt_tokens": 0, "completion_tokens": 0, "grounding_flagged": False,
            }
            return update, decision.model_dump(), "ok"

        return await self._stage("router", work)

    # ---- 2. Semantic cache ---------------------------------------------------------------
    async def semantic_cache(self, state: State) -> dict[str, Any]:
        async def work():
            cache = self.ctx.cache_for(self.req.session_id, self.req.domain)
            result = await asyncio.to_thread(cache.lookup, state["query_vec"])
            if result.hit and (result.value or {}).get("card", {}).get("kind") != state["router"].card_kind:
                result.hit = False  # same wording, different task type: not a valid reuse
            lookup = CacheLookup(
                hit=result.hit, similarity=None if result.similarity is None else round(result.similarity, 4),
                threshold=self.ctx.settings.cache_threshold, backend=result.backend,  # type: ignore[arg-type]
                matched_query=result.matched_query,
            )
            update: dict[str, Any] = {"cache": lookup}
            if result.hit and result.value:
                update.update(
                    card=result.value["card"], triad=TriadScores(**result.value["eval"]), chunks=[], draft="",
                    critic=CriticVerdict(passed=True, faithfulness=result.value["eval"]["faithfulness"], flagged_claims=[]),
                )
            return update, lookup.model_dump(), "ok"

        update = await self._stage("cache", work)
        if update["cache"].hit:
            for node in ("retriever", "generator", "critic"):
                await self.emit("node_end", node=node, latency_ms=0.0, status="skipped", data={}, attempt=0)
        return update

    # ---- 3. Hybrid retriever -------------------------------------------------------------
    async def retriever(self, state: State) -> dict[str, Any]:
        async def work():
            # k=2 only when the router itself chose the cheap tier; a user-forced model keeps full retrieval depth.
            k = 4 if (state["router"].tier == "70b" or self.req.model_mode != "auto") else 2
            hits = await asyncio.to_thread(
                self.setup.runtime.retriever.retrieve, state["sanitized"], k, 10, "hybrid", state["query_vec"], True
            )
            chunks = [
                RetrievedChunk(
                    chunk_id=h.chunk.chunk_id, doc_id=h.chunk.doc_id, doc_title=h.chunk.doc_title,
                    section=h.chunk.section, text=h.chunk.text,
                    dense_score=None if h.dense_score is None else round(h.dense_score, 4),
                    bm25_score=None if h.bm25_score is None else round(h.bm25_score, 4),
                    rrf_score=round(h.rrf_score, 5), rank=h.rank,
                )
                for h in hits
            ]
            return {"chunks": chunks}, {"chunks": [c.model_dump() for c in chunks]}, "ok"

        return await self._stage("retriever", work)

    # ---- 4. Generator --------------------------------------------------------------------
    async def generator(self, state: State) -> dict[str, Any]:
        attempt = state.get("attempt", 0)

        async def work():
            router = state["router"]
            llm_req = LLMRequest(
                role="generator", tier=router.tier, query=state["sanitized"], preset_id=self.req.preset_id,
                card_kind=router.card_kind, chunks=state["chunks"], attempt=attempt,
                feedback=state.get("feedback", []), injection_patterns=router.injection_patterns,
                domain=self.req.domain, preset_kind=self.setup.preset_kind,
            )
            text, usage, fb = await stream_tokens(
                self.ctx, self.run, llm_req, self.emit, reset_first=attempt > 0, chunks=state["chunks"]
            )
            # Per-attempt accounting: a Critic retry adds its own (provider-counted when live) tokens.
            update = {
                "draft": text,
                "prompt_tokens": state.get("prompt_tokens", 0) + usage.prompt_tokens,
                "completion_tokens": state.get("completion_tokens", 0) + usage.completion_tokens,
                "usage_sources": [*state.get("usage_sources", []), usage.source],
                "fallback_reason": fb or state.get("fallback_reason"),
            }
            return update, {"usage": usage.model_dump(), "model": router.model}, "ok"

        return await self._stage("generator", work, attempt=attempt)

    # ---- 5. Hallucination critic ---------------------------------------------------------
    async def critic(self, state: State) -> dict[str, Any]:
        attempt = state.get("attempt", 0)

        async def work():
            kind = state["router"].card_kind
            flagged: list[str] = []
            unsupported: list[str] = []
            try:
                payload = parse_json_object(state["draft"])
            except json.JSONDecodeError:
                payload = None
                flagged.append("Output is not valid JSON")
            faithfulness = 0.0
            if payload is not None:
                context = "\n".join(c.text for c in state["chunks"])
                # Calculator-derived figures (answer key) count as supported: "derivable", not only "quoted".
                context += "\n" + expected_text(self.setup.expected)
                g = evaluate_grounding(payload, context, state["sanitized"])
                faithfulness, unsupported = g.faithfulness, g.unsupported
                known = {c.chunk_id for c in state["chunks"]}
                for cid in payload.get("citations", []) if isinstance(payload, dict) else []:
                    if cid not in known:
                        unsupported.append(f"Cites {cid}, which was not retrieved")
                flagged.extend(unsupported)
                try:
                    CARD_MODELS[kind].model_validate(payload)
                except ValidationError as e:
                    flagged.extend(f"Schema: {m}" for m in _validation_messages(e))
            passed = not flagged and faithfulness >= FAITHFULNESS_THRESHOLD
            verdict = CriticVerdict(
                passed=passed, faithfulness=faithfulness, flagged_claims=flagged,
                retry_requested=(not passed and attempt < MAX_RETRIES),
            )
            update: dict[str, Any] = {
                "critic": verdict, "faithfulness": faithfulness, "unsupported": unsupported,
                "grounding_flagged": state.get("grounding_flagged", False) or bool(unsupported),
            }
            if verdict.retry_requested:
                update.update(attempt=attempt + 1, feedback=flagged)
            return update, verdict.model_dump(), "ok" if passed else "error"

        return await self._stage("critic", work, attempt=attempt)

    # ---- 6. Pydantic validator + RAG-triad eval ------------------------------------------
    async def validator(self, state: State) -> dict[str, Any]:
        async def work():
            cache_hit = state["cache"].hit
            kind = state["router"].card_kind
            errors: list[str] = []
            card: dict[str, Any] | None = None
            try:
                payload = state["card"] if cache_hit else parse_json_object(state["draft"])
                model = CARD_MODELS[kind].model_validate(payload)
                card = model.model_dump(mode="json")
                raw_json = model.model_dump_json(indent=2)
            except json.JSONDecodeError:
                errors.append("Output is not valid JSON")
            except ValidationError as e:
                errors.extend(_validation_messages(e))
            valid = card is not None

            chunks = state.get("chunks", [])
            if cache_hit:
                triad = state["triad"].model_copy(update={"schema_validity": 1.0 if valid else 0.0})
            else:
                triad = score_triad(
                    query=state["sanitized"], chunks=chunks, faithfulness=state.get("faithfulness", 0.0),
                    unsupported=state.get("unsupported", []), schema_valid=valid, preset=self.setup.facts(),
                )
            if valid:
                await self.emit("card", card=card, raw_json=raw_json)
                critic_ok = state["critic"].passed
                if not cache_hit and critic_ok:
                    cache = self.ctx.cache_for(self.req.session_id, self.req.domain)
                    await asyncio.to_thread(
                        cache.store, state["sanitized"], state["query_vec"], {"card": card, "eval": triad.model_dump()}
                    )
            await self.emit("eval", **triad.model_dump())
            return {"card": card, "schema_valid": valid, "triad": triad}, {"valid": valid, "errors": errors}, (
                "ok" if valid else "error"
            )

        return await self._stage("validator", work)
