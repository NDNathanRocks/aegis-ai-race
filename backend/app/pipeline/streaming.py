"""Shared LLM token streaming: batching (<= ~30 frames/s), running cost, fallback signalling."""
import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.cost import cost_usd, estimate_tokens, make_usage
from app.deps import AppContext
from app.llm.base import LLMRequest, Reset, build_messages
from app.schemas import TokenUsage
from app.sse import Emitter

Emit = Callable[..., Awaitable[None]]
FLUSH_INTERVAL_S = 0.033


async def stream_tokens(
    ctx: AppContext, req: LLMRequest, emit: Emit, *, force_demo: bool, reset_first: bool = False
) -> tuple[str, TokenUsage, str | None]:
    """Run one LLM call, emitting `token` events. Returns (text, usage, fallback_reason)."""
    prompt_tokens = sum(estimate_tokens(m["content"]) for m in build_messages(req))
    usd_per_m = ctx.settings.enterprise_usd_per_million
    fallbacks: list[str] = []
    req.on_fallback = fallbacks.append
    text, buffer = "", ""
    reset_pending = reset_first
    fallback_sent = False
    last_flush = 0.0

    async def flush() -> None:
        nonlocal buffer, reset_pending, last_flush
        if not buffer and not reset_pending:
            return
        completion = estimate_tokens(text)
        await emit(
            "token",
            text=buffer,
            reset=reset_pending,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion,
            cost_usd=cost_usd(prompt_tokens + completion, req.tier, usd_per_m),
        )
        buffer, reset_pending, last_flush = "", False, time.monotonic()

    async def announce_fallback() -> None:
        nonlocal fallback_sent
        if fallbacks and not fallback_sent:
            fallback_sent = True
            await emit("fallback", reason=fallbacks[0], switched_to="demo")

    async for piece in ctx.llm.stream(req, force_demo):
        await announce_fallback()
        if isinstance(piece, Reset):
            text, buffer, reset_pending = "", "", True
            await flush()
            continue
        text += piece
        buffer += piece
        if time.monotonic() - last_flush >= FLUSH_INTERVAL_S:
            await flush()
    await announce_fallback()
    await flush()
    return text, make_usage(prompt_tokens, estimate_tokens(text), req.tier, usd_per_m), (fallbacks[0] if fallbacks else None)


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
