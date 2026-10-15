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
        # Loads the ONNX model and builds/loads the vector index before serving traffic.
        app.state.ctx = await asyncio.to_thread(build_context, settings)
        app.state.limiter = RateLimiter(settings.rate_limit_per_min)
        yield

    app = FastAPI(title="Aegis: Naive AI vs Engineered AI", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        max_age=600,
    )
    app.include_router(meta.router, prefix="/api")
    app.include_router(race.router, prefix="/api")
    return app


app = create_app()
