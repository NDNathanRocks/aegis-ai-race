"""LangGraph state machine + the SSE-facing runner for the engineered side."""
from collections.abc import AsyncIterator
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.cost import make_usage
from app.deps import AppContext
from app.llm.gateway import RaceRun
from app.pipeline.naive import meta_fields
from app.pipeline.nodes import Nodes, State
from app.pipeline.setup import RaceSetup, make_setup, verdict_dict
from app.pipeline.streaming import Emit, EventPump
from app.schemas import RaceRequest
from app.sse import Emitter


def build_graph(setup: RaceSetup, emit: Emit):
    n = Nodes(setup, emit)
    g = StateGraph(State)
    g.add_node("router", n.router)
    g.add_node("cache", n.semantic_cache)
    g.add_node("retriever", n.retriever)
    g.add_node("generator", n.generator)
    g.add_node("critic", n.critic)
    g.add_node("validator", n.validator)

    g.add_edge(START, "router")
    g.add_edge("router", "cache")
    g.add_conditional_edges("cache", lambda s: "validator" if s["cache"].hit else "retriever")
    g.add_edge("retriever", "generator")
    g.add_edge("generator", "critic")
    g.add_conditional_edges("critic", lambda s: "generator" if s["critic"].retry_requested else "validator")
    g.add_edge("validator", END)
    return g.compile()


def _model_label(setup: RaceSetup) -> str:
    s = setup.ctx.settings
    if setup.req.model_mode == "auto":
        return f"{s.groq_fast_model} / {s.groq_heavy_model} (routed)"
    return setup.model_for("70b" if setup.req.model_mode == "70b" else "8b")


async def run_engineered(
    ctx: AppContext, req: RaceRequest, em: Emitter, run: RaceRun | None = None
) -> AsyncIterator[dict[str, Any]]:
    s = ctx.settings
    run = run or ctx.llm.run_for(req.race_id, "anon", req.force_demo)
    setup = make_setup(ctx, req, run)
    yield em.event("meta", **meta_fields(setup, _model_label(setup)))
    yield em.event("race_state", degraded=run.degraded, reason=run.degraded_reason, provider=run.provider)
    if run.degraded:
        run.take_notification("engineered")

    pump = EventPump(em)
    graph = build_graph(setup, pump.emit)
    async for event in pump.run(graph.ainvoke({})):
        yield event
    final: State = pump.result
    router, cache = final["router"], final["cache"]
    sources = final.get("usage_sources", [])  # one entry per generator attempt; empty on a cache hit (exact zero)
    usage = make_usage(
        final.get("prompt_tokens", 0), final.get("completion_tokens", 0), router.tier, s.enterprise_usd_per_million,
        "provider" if all(x == "provider" for x in sources) else "estimate", s.cost_ratio_8b,
    )

    # Deterministic answer-key verdict on the validated card (or the raw draft if the card never validated).
    card = final.get("card")
    verdict = verdict_dict(card if card is not None else final.get("draft", ""), setup.expected)
    if not verdict["key_applies"]:
        verdict["correct"] = bool(card is not None and final["critic"].passed)
    yield em.event("verdict", **verdict)
    if run.degraded and run.take_notification("engineered"):
        yield em.event("race_state", degraded=True, reason=run.degraded_reason, provider=run.provider)
    live = run.mode == "live" and not run.degraded and not final.get("fallback_reason")
    yield em.event(
        "done",
        total_ms=em.ms(),
        usage=usage.model_dump(),
        cache_hit=cache.hit,
        hallucination_prevented=bool(final.get("grounding_flagged")),
        mode="live" if live else "demo",
        degraded=run.degraded,
    )
