"""Shared LLM token streaming: batching (<= ~30 frames/s), running cost, payload/status/race_state events,
real (provider) usage with per-attempt accounting."""
import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.cost import cost_usd, estimate_tokens, make_usage
from app.deps import AppContext
from app.llm.base import LLMRequest, RaceStateChange, Reset, Status, Usage, build_payload
from app.llm.gateway import RaceRun
from app.schemas import RetrievedChunk, TokenUsage
from app.sse import Emitter

Emit = Callable[..., Awaitable[None]]
FLUSH_INTERVAL_S = 0.033


async def emit_race_state(emit: Emit, state: RaceStateChange) -> None:
    await emit("race_state", degraded=state.degraded, reason=state.reason, provider=state.provider)


async def stream_tokens(
    ctx: AppContext,
    run: RaceRun,
    req: LLMRequest,
    emit: Emit,
    *,
    reset_first: bool = False,
    chunks: list[RetrievedChunk] | None = None,
) -> tuple[str, TokenUsage, str | None]:
    """Run one LLM call, emitting `payload` then `token` events. Returns (text, usage, fallback_reason).

    `usage` is the provider's count for this attempt when Groq answered (source="provider"), otherwise an
    estimate (source="estimate"). If the call restarted (Reset), only the final successful attempt is counted.
    """
    s = ctx.settings
    messages, composition = build_payload(req)
    prompt_est = sum(estimate_tokens(m["content"]) for m in messages)
    model = ctx.llm.model_name(req)
    payload: dict[str, Any] = dict(
        attempt=req.attempt, model=model, messages=messages, token_count=prompt_est, token_source="estimate",
        composition=composition,
    )
    if chunks is not None:
        payload["chunks"] = [c.model_dump() for c in chunks]
    await emit("payload", **payload)

    usd_per_m, ratio = s.enterprise_usd_per_million, s.cost_ratio_8b
    fallbacks: list[str] = []
    req.on_fallback = fallbacks.append
    text, buffer = "", ""
    reset_pending = reset_first
    fallback_sent = False
    last_flush = 0.0
    final: Usage | None = None

    async def flush() -> None:
        nonlocal buffer, reset_pending, last_flush
        if not buffer and not reset_pending:
            return
        completion = estimate_tokens(text)
        await emit(
            "token",
            text=buffer,
            reset=reset_pending,
            prompt_tokens=prompt_est,
            completion_tokens=completion,
            cost_usd=cost_usd(prompt_est + completion, req.tier, usd_per_m, ratio),
        )
        buffer, reset_pending, last_flush = "", False, time.monotonic()

    async def announce_fallback() -> None:
        nonlocal fallback_sent
        if fallbacks and not fallback_sent:
            fallback_sent = True
            await emit("fallback", reason=fallbacks[0], switched_to="demo")

    stream: AsyncIterator[Any] = ctx.llm.stream(run, req)
    async for piece in stream:
        await announce_fallback()
        if isinstance(piece, Status):
            await flush()
            await emit("status", phase=piece.phase, detail=piece.detail, wait_ms=piece.wait_ms)
        elif isinstance(piece, RaceStateChange):
            await flush()
            await emit_race_state(emit, piece)
        elif isinstance(piece, Usage):
            final = piece
        elif isinstance(piece, Reset):
            text, buffer, reset_pending, final = "", "", True, None
            await flush()
        else:
            text += piece
            buffer += piece
            if time.monotonic() - last_flush >= FLUSH_INTERVAL_S:
                await flush()
    await announce_fallback()
    await flush()
    if final is not None:
        usage = make_usage(final.prompt_tokens, final.completion_tokens, req.tier, usd_per_m, final.source, ratio)
    else:
        usage = make_usage(prompt_est, estimate_tokens(text), req.tier, usd_per_m, "estimate", ratio)
    return text, usage, (fallbacks[0] if fallbacks else None)


async def sync_race_state(run: RaceRun, side: str, emit: Emit) -> None:
    """Make sure this side has told the client about a degraded race (e.g. the sibling gave up first)."""
    if run.degraded and run.take_notification(side):
        await emit_race_state(emit, run.state_event())


class EventPump:
    """Runs a coroutine that emits events, and yields those events as they are produced."""

    def __init__(self, em: Emitter):
        self.em = em
        self._q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.result: Any = None

    async def emit(self, type_: str, **payload: Any) -> None:
        await self._q.put(self.em.event(type_, **payload))

    async def run(self, coro: Awaitable[Any]) -> AsyncIterator[dict[str, Any]]:
        task = asyncio.ensure_future(coro)
        task.add_done_callback(lambda _t: self._q.put_nowait(None))
        try:
            while (item := await self._q.get()) is not None:
                yield item
            self.result = task.result()  # re-raises any failure from the coroutine
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
