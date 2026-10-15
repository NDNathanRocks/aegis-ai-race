"""Application context (shared singletons) and the per-IP rate limiter."""
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

import numpy as np

from app.config import Settings
from app.llm.factory import ResilientLLM
from app.rag.cache import SemanticCache, build_cache
from app.rag.corpus import Chunk, corpus_version, load_chunks
from app.rag.embeddings import Embedder, get_embedder
from app.rag.hybrid import HybridRetriever, build_retriever

MAX_SESSIONS = 256

_COMPLEX_PROTOTYPES = [
    "Audit this invoice and compute the discrepancy against the contract terms",
    "Compare several policies and explain the reasoning step by step",
]
_SIMPLE_PROTOTYPES = [
    "Classify this ticket into a category and priority",
    "Reformat this short text",
    "What is a single fact from the policy",
]


@dataclass
class AppContext:
    settings: Settings
    embedder: Embedder
    chunks: list[Chunk]
    retriever: HybridRetriever
    llm: ResilientLLM
    version: str
    _caches: OrderedDict[str, SemanticCache] = field(default_factory=OrderedDict)
    _protos: tuple[np.ndarray, np.ndarray] | None = None

    def cache_for(self, session_id: str | None) -> SemanticCache:
        """Per-session semantic cache so one visitor's demo never pre-warms another's."""
        key = session_id or "global"
        if key in self._caches:
            self._caches.move_to_end(key)
            return self._caches[key]
        cache = build_cache(self.settings, f"{self.version}:{key}")
        self._caches[key] = cache
        while len(self._caches) > MAX_SESSIONS:
            self._caches.popitem(last=False)
        return cache

    def reset_cache(self, session_id: str | None) -> None:
        self.cache_for(session_id).clear()

    def prototypes(self) -> tuple[np.ndarray, np.ndarray]:
        if self._protos is None:
            self._protos = (
                self.embedder.embed(_COMPLEX_PROTOTYPES),
                self.embedder.embed(_SIMPLE_PROTOTYPES),
            )
        return self._protos


def build_context(settings: Settings) -> AppContext:
    embedder = get_embedder(settings.embedding_backend, settings.embedding_model)
    chunks = load_chunks(settings.corpus_dir)
    retriever = build_retriever(settings, embedder, chunks)
    ctx = AppContext(settings, embedder, chunks, retriever, ResilientLLM(settings), corpus_version(settings.corpus_dir))
    ctx.prototypes()  # warm
    return ctx


class RateLimiter:
    """Sliding-window limiter, per client key. In-memory: fine for a single instance."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> float | None:
        """Returns None if allowed, else seconds until the client may retry."""
        now = time.monotonic()
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return max(1.0, 60 - (now - q[0]))
        q.append(now)
        if len(self._hits) > 5000:  # bound memory
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 60]:
                del self._hits[k]
        return None
