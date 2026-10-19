from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import domains as dom
from app.pipeline.graph import run_engineered
from app.pipeline.naive import run_naive
from app.schemas import RaceRequest
from app.sse import SSE_HEADERS, Emitter, sse_stream

router = APIRouter()


def client_key(request: Request) -> str:
    """Rate-limit identity. X-Forwarded-For is attacker-controlled unless a proxy we run appended to it, so it is
    honoured only when TRUST_PROXY=1, and then only the entry our own proxy(ies) added (the right-most hops)."""
    settings = request.app.state.ctx.settings
    fwd = request.headers.get("x-forwarded-for")
    if fwd and settings.trust_proxy:
        hops = [h.strip() for h in fwd.split(",") if h.strip()]
        if hops:
            return hops[max(0, len(hops) - max(1, settings.trusted_proxy_hops))]
    return request.client.host if request.client else "unknown"


@router.post("/race/{side}")
async def race(side: Literal["naive", "engineered"], body: RaceRequest, request: Request) -> StreamingResponse:
    state = request.app.state
    ctx = state.ctx
    # preset_id is validated against the requested domain's presets (legacy B2B ids and aliases included).
    if body.preset_id and dom.get_preset(body.domain, body.preset_id) is None:
        raise HTTPException(422, f"Unknown preset_id for domain {body.domain}")
    if body.domain not in ctx.domains:
        raise HTTPException(503, f"Domain {body.domain} is not loaded")
    key = client_key(request)
    retry_after = state.limiter.check(key)
    if retry_after is not None:
        raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": str(int(retry_after) + 1)})
    # The provider for the whole race is decided here, once, by whichever side arrives first.
    run = ctx.llm.run_for(body.race_id, key, body.force_demo)
    em = Emitter(side)
    runner = run_naive if side == "naive" else run_engineered
    return StreamingResponse(
        sse_stream(runner(ctx, body, em, run), em), media_type="text/event-stream", headers=SSE_HEADERS
    )
