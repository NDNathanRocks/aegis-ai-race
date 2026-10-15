"""LangGraph state machine + the SSE-facing runner for the engineered side."""
from collections.abc import AsyncIterator
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.cost import make_usage
from app.deps import AppContext
from app.pipeline.nodes import Nodes, State
from app.pipeline.streaming import Emit, EventPump
from app.schemas import RaceRequest
from app.sse import Emitter


def build_graph(ctx: AppContext, req: RaceRequest, emit: Emit):
    n = Nodes(ctx, req, emit)
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


async def run_engineered(ctx: AppContext, req: RaceRequest, em: Emitter) -> AsyncIterator[dict[str, Any]]:
    s = ctx.settings
    mode, reason = ctx.llm.mode(req.force_demo)
    yield em.event(
        "meta", mode=mode, query=req.query, preset_id=req.preset_id,
        model=f"{s.groq_fast_model} / {s.groq_heavy_model} (routed)", fallback_reason=reason,
    )
    pump = EventPump(em)
    graph = build_graph(ctx, req, pump.emit)
    async for event in pump.run(graph.ainvoke({})):
        yield event
    final: State = pump.result
    router, cache = final["router"], final["cache"]
    usage = make_usage(
        final.get("prompt_tokens", 0), final.get("completion_tokens", 0), router.tier, s.enterprise_usd_per_million
    )
    yield em.event(
        "done",
        total_ms=em.ms(),
        usage=usage.model_dump(),
        cache_hit=cache.hit,
        hallucination_prevented=bool(final.get("grounding_flagged")),
        mode="demo" if final.get("fallback_reason") else mode,
    )
