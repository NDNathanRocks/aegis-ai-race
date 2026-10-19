"""Application context (shared singletons) and the per-IP rate limiter."""
import hashlib
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

import numpy as np

from app import domains as dom
from app.config import Settings
from app.llm.gateway import LLMGateway
from app.rag.cache import SemanticCache, build_cache
from app.rag.embeddings import Embedder, get_embedder

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
    domains: dict[str, dom.DomainRuntime]
    llm: LLMGateway
    version: str
    _caches: OrderedDict[tuple[str, str], SemanticCache] = field(default_factory=OrderedDict)
    _protos: tuple[np.ndarray, np.ndarray] | None = None

    def runtime(self, domain: str) -> dom.DomainRuntime:
        try:
            return self.domains[domain]
        except KeyError:
            raise KeyError(f"domain {domain!r} is not loaded") from None

    def cache_for(self, session_id: str | None, domain: str = "b2b_sla") -> SemanticCache:
        """Per-(domain, session) semantic cache: namespace `version:domain:session`, so one visitor's demo never
        pre-warms another's and a cached card never crosses knowledge bases."""
        key = (domain, session_id or "global")
        if key in self._caches:
            self._caches.move_to_end(key)
            return self._caches[key]
        cache = build_cache(self.settings, f"{self.version}:{domain}:{key[1]}")
        self._caches[key] = cache
        while len(self._caches) > MAX_SESSIONS * 4:
            self._caches.popitem(last=False)
        return cache

    def reset_cache(self, session_id: str | None) -> None:
        """Clear the session's cache in every domain."""
        sid = session_id or "global"
        for d in list(self.domains) or ["b2b_sla"]:
            self.cache_for(sid, d).clear()

    def prototypes(self) -> tuple[np.ndarray, np.ndarray]:
        if self._protos is None:
            self._protos = (
                self.embedder.embed(_COMPLEX_PROTOTYPES),
                self.embedder.embed(_SIMPLE_PROTOTYPES),
            )
        return self._protos


def build_context(settings: Settings) -> AppContext:
    embedder = get_embedder(settings.embedding_backend, settings.embedding_model)
    domains = dom.build_domains(settings, embedder)
    h = hashlib.sha256()
    for d in sorted(domains):
        h.update(d.encode())
        h.update(domains[d].spec.kb_text.encode())
    ctx = AppContext(settings, embedder, domains, LLMGateway(settings), h.hexdigest()[:12])
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
