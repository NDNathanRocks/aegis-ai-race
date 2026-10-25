import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import meta, race
from app.config import Settings, get_settings
from app.deps import RateLimiter, build_context


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Loads the ONNX model, builds/loads per-domain vector indexes and pre-populates the query caches
        # (build_domains warms every preset query/paraphrase) before serving traffic; /api/health reports `ready`.
        app.state.ready = False
        app.state.ctx = await asyncio.to_thread(build_context, settings)
        app.state.limiter = RateLimiter(settings.rate_limit_per_min)
        app.state.ready = True
        yield

    app = FastAPI(title="Aegis: Naive AI vs Engineered AI", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["Retry-After"],  # read by the frontend 429 countdown; hidden cross-origin otherwise
        max_age=600,
    )
    app.include_router(meta.router, prefix="/api")
    app.include_router(race.router, prefix="/api")
    return app


app = create_app()
