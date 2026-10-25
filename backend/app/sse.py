"""Server-Sent Events helpers: framing, heartbeat, run clock."""
import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable nginx/HF proxy buffering
}
HEARTBEAT_S = 15.0
log = logging.getLogger("aegis.sse")


class Emitter:
    """Stamps every event with run_id, side and server-side elapsed milliseconds."""

    def __init__(self, side: str):
        self.side = side
        self.run_id = uuid.uuid4().hex[:12]
        self._t0 = time.perf_counter()

    def ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 2)

    def event(self, type_: str, **payload: Any) -> dict[str, Any]:
        return {"event": type_, "data": {"run_id": self.run_id, "side": self.side, "t_ms": self.ms(), **payload}}


def format_sse(event: dict[str, Any]) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event['data'], default=str)}\n\n"


async def sse_stream(events: AsyncIterator[dict[str, Any]], emitter: Emitter) -> AsyncIterator[str]:
    """Frame events, emit heartbeats while idle, and always terminate with `done` or `error`."""
    it = events.__aiter__()
    pending: asyncio.Task | None = None
    terminated = False
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(it.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=HEARTBEAT_S)
            if not done:
                yield ": ping\n\n"
                continue
            task, pending = pending, None
            try:
                event = task.result()
            except StopAsyncIteration:
                break
            yield format_sse(event)
            if event["event"] in ("done", "error"):
                terminated = True
        if not terminated:
            yield format_sse(emitter.event("error", code="no_terminal_event", message="stream ended early", recoverable=True))
    except asyncio.CancelledError:
        raise
    except Exception:  # never leave the client hanging without a terminal frame; details stay in the server log
        log.exception("race stream failed (run_id=%s side=%s)", emitter.run_id, emitter.side)
        yield format_sse(
            emitter.event("error", code="internal_error", message="Internal error while streaming", recoverable=False)
        )
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        aclose = getattr(it, "aclose", None)
        if aclose:
            try:
                await aclose()
            except Exception:
                pass
