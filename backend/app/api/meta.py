from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.presets import PRESETS
from app.rag.corpus import load_documents

router = APIRouter()


class CacheResetBody(BaseModel):
    session_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/config")
async def config(request: Request) -> dict:
    ctx = request.app.state.ctx
    mode, reason = ctx.llm.mode()
    return {
        "mode": mode,
        "fallback_reason": reason,
        "cache_backend": ctx.cache_for(None).backend,
        "vector_backend": "pgvector" if ctx.settings.database_url else "local",
        "embedding_model": ctx.embedder.name,
        "cache_threshold": ctx.settings.cache_threshold,
        "usd_per_million_tokens": ctx.settings.enterprise_usd_per_million,
        "corpus_version": ctx.version,
        "chunks": len(ctx.chunks),
    }


@router.get("/presets")
async def presets() -> list[dict]:
    return [
        {k: v for k, v in asdict(p).items() if k not in ("wrong_markers", "expected_facts")} for p in PRESETS.values()
    ]


@router.get("/kb/documents")
async def kb_documents(request: Request) -> list[dict]:
    docs = load_documents(request.app.state.ctx.settings.corpus_dir)
    return [{"id": d.id, "title": d.title, "category": d.category, "words": len(d.text.split())} for d in docs]


@router.get("/kb/documents/{doc_id}")
async def kb_document(doc_id: str, request: Request) -> dict:
    for d in load_documents(request.app.state.ctx.settings.corpus_dir):
        if d.id == doc_id:
            return {"id": d.id, "title": d.title, "category": d.category, "text": d.text}
    raise HTTPException(404, "Document not found")


@router.post("/cache/reset")
async def cache_reset(body: CacheResetBody, request: Request) -> dict:
    request.app.state.ctx.reset_cache(body.session_id)
    return {"ok": True}

