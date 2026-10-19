from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import domains as dom
from app.presets import PRESETS
from app.rag.corpus import load_documents

router = APIRouter()

DEFAULT_DOMAIN = "b2b_sla"


class CacheResetBody(BaseModel):
    session_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _ctx(request: Request):
    return request.app.state.ctx


def _domain_dir(request: Request, domain: str):
    """Only domains the server has loaded are addressable, so `domain` can never be a path."""
    ctx = _ctx(request)
    if domain not in ctx.domains:
        raise HTTPException(404, "Unknown domain")
    return ctx.settings.corpus_dir / domain


@router.get("/health")
async def health(request: Request) -> dict:
    ctx = getattr(request.app.state, "ctx", None)
    ready = bool(ctx is not None and getattr(request.app.state, "ready", True))
    return {"status": "ok", "ready": ready}


@router.get("/config")
async def config(request: Request) -> dict:
    ctx = _ctx(request)
    mode, reason = ctx.llm.mode()
    first = next(iter(ctx.domains.values()), None)
    index = getattr(getattr(first, "retriever", None), "vector_index", None)
    # Deliberately no secrets here: only whether a key is configured is implied by `mode`.
    return {
        "mode": mode,
        "fallback_reason": reason,
        "cache_backend": ctx.cache_for(None).backend,
        "vector_backend": "pgvector" if type(index).__name__ == "PgVectorIndex" else "local",
        "embedding_model": ctx.embedder.name,
        "cache_threshold": ctx.settings.cache_threshold,
        "usd_per_million_tokens": ctx.settings.enterprise_usd_per_million,
        "corpus_version": ctx.version,
        "chunks": sum(len(r.chunks) for r in ctx.domains.values()),
        "domains": list(ctx.domains),
        "models": {"70b": ctx.settings.groq_heavy_model, "8b": ctx.settings.groq_fast_model},
    }


@router.get("/domains")
async def domains(request: Request) -> list[dict]:
    ctx = _ctx(request)
    out = []
    for spec in dom.list_domains():
        if spec.id not in ctx.domains:
            continue
        try:
            doc_count = len(load_documents(ctx.settings.corpus_dir / spec.id))
        except (OSError, ValueError, KeyError):
            doc_count = len({c.doc_id for c in ctx.domains[spec.id].chunks})
        out.append({
            "id": spec.id, "title": spec.title, "emoji": spec.emoji, "blurb": spec.blurb,
            "kb_tokens": spec.kb_tokens,  # estimate (~4 chars/token)
            "doc_count": doc_count,
            "presets": [
                {
                    "id": p.id, "kind": p.kind, "title": p.title, "tagline": p.tagline, "query": p.query,
                    "paraphrase": p.paraphrase, "card_kind": p.card_kind,
                }
                for p in spec.presets
            ],
        })
    return out


@router.get("/presets")
async def presets(domain: str | None = None) -> list[dict]:
    """Legacy flat B2B preset list (unchanged shape); `?domain=` returns that domain's presets instead."""
    if domain:
        try:
            spec = dom.get_domain(domain)
        except KeyError:
            raise HTTPException(404, "Unknown domain") from None
        return [
            {k: v for k, v in asdict(p).items() if k not in ("wrong_markers", "expected_facts")} for p in spec.presets
        ]
    return [
        {k: v for k, v in asdict(p).items() if k not in ("wrong_markers", "expected_facts")} for p in PRESETS.values()
    ]


@router.get("/kb/{domain}/documents")
async def kb_documents(domain: str, request: Request) -> list[dict]:
    docs = load_documents(_domain_dir(request, domain))
    return [{"id": d.id, "title": d.title, "category": d.category, "words": len(d.text.split())} for d in docs]


@router.get("/kb/{domain}/documents/{doc_id}")
async def kb_document(domain: str, doc_id: str, request: Request) -> dict:
    for d in load_documents(_domain_dir(request, domain)):
        if d.id == doc_id:
            return {"id": d.id, "title": d.title, "category": d.category, "text": d.text}
    raise HTTPException(404, "Document not found")


# Pre-v2 routes: the B2B knowledge base.
@router.get("/kb/documents")
async def kb_documents_legacy(request: Request) -> list[dict]:
    return await kb_documents(DEFAULT_DOMAIN, request)


@router.get("/kb/documents/{doc_id}")
async def kb_document_legacy(doc_id: str, request: Request) -> dict:
    return await kb_document(DEFAULT_DOMAIN, doc_id, request)


@router.post("/cache/reset")
async def cache_reset(body: CacheResetBody, request: Request) -> dict:
    _ctx(request).reset_cache(body.session_id)
    return {"ok": True}
