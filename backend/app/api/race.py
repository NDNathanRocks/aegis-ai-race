from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.pipeline.graph import run_engineered
from app.pipeline.naive import run_naive
from app.schemas import RaceRequest
from app.sse import SSE_HEADERS, Emitter, sse_stream

router = APIRouter()


def _client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/race/{side}")
async def race(side: Literal["naive", "engineered"], body: RaceRequest, request: Request) -> StreamingResponse:
    state = request.app.state
    retry_after = state.limiter.check(_client_key(request))
    if retry_after is not None:
        raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": str(int(retry_after) + 1)})
    em = Emitter(side)
    runner = run_naive if side == "naive" else run_engineered
    return StreamingResponse(
        sse_stream(runner(state.ctx, body, em), em), media_type="text/event-stream", headers=SSE_HEADERS
    )
