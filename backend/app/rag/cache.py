"""Semantic cache: Redis-backed with automatic in-memory NumPy fallback."""
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

import numpy as np

log = logging.getLogger("aegis.cache")

_FIGURE = re.compile(r"(\d[\d,]*(?:\.\d+)?)(\s?(?:%|percent\b|per cent\b))?", re.I)


def query_figures(text: str) -> list[str]:
    """Every number in a query, normalised (1,000 == 1000.0, 99.7 percent == 99.7%) and sorted."""
    return sorted(f"{Decimal(m[1].replace(',', '')).normalize():f}{'%' if m[2] else ''}" for m in _FIGURE.finditer(text))


def figures_match(a: str, b: str) -> bool:
    """Embeddings barely register numbers: changing 99.62% to 99.92% in a long prompt keeps cosine at ~1.0
    (docs/cache-threshold.md). A cached answer is reused only when both queries contain the same figures."""
    return query_figures(a) == query_figures(b)


@dataclass
class CacheResult:
    hit: bool
    similarity: float | None
    matched_query: str | None
    value: dict[str, Any] | None
    backend: str


class SemanticCache(Protocol):
    backend: str

    def lookup(self, vec: np.ndarray) -> CacheResult: ...
    def store(self, query: str, vec: np.ndarray, value: dict[str, Any]) -> None: ...
    def clear(self) -> None: ...
    def __len__(self) -> int: ...


class MemorySemanticCache:
    """Bounded to the newest `max_entries` (session ids are client-chosen). lookup/store run in worker threads
    via asyncio.to_thread, so each entry is one tuple and the list is guarded by a lock."""

    backend = "memory"

    def __init__(self, threshold: float = 0.92, max_entries: int = 200):
        self.threshold = threshold
        self.max_entries = max_entries
        self._rows: list[tuple[np.ndarray, str, dict[str, Any]]] = []
        self._lock = threading.Lock()

    def lookup(self, vec: np.ndarray) -> CacheResult:
        with self._lock:
            rows = list(self._rows)
        if not rows:
            return CacheResult(False, None, None, None, self.backend)
        sims = np.stack([r[0] for r in rows]) @ vec
        i = int(np.argmax(sims))
        sim = float(sims[i])
        if sim >= self.threshold:
            _, q, v = rows[i]
            return CacheResult(True, sim, q, v, self.backend)
        return CacheResult(False, sim, None, None, self.backend)

    def store(self, query: str, vec: np.ndarray, value: dict[str, Any]) -> None:
        with self._lock:
            self._rows.append((vec.astype(np.float32), query, value))
            if len(self._rows) > self.max_entries:
                del self._rows[: len(self._rows) - self.max_entries]

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()

    def __len__(self) -> int:
        return len(self._rows)


class RedisSemanticCache:
    """Entries are Redis hashes under `aegis:sc:<namespace>:<id>` with a TTL.

    Similarity is computed client-side over the (small) namespace, so this works
    on plain Redis with no RediSearch module.
    """

    backend = "redis"

    def __init__(self, client, threshold: float = 0.92, namespace: str = "", ttl_s: int = 3600):
        self.client = client
        self.threshold = threshold
        self.ttl_s = ttl_s
        self.prefix = f"aegis:sc:{namespace}:"
        self.client.ping()  # raises if unreachable -> caller falls back to memory

    def _keys(self) -> list:
        return list(self.client.scan_iter(match=self.prefix + "*", count=200))

    def lookup(self, vec: np.ndarray) -> CacheResult:
        """A Redis failure after construction degrades to a miss; it never fails the pipeline stage."""
        try:
            keys = self._keys()
            pipe = self.client.pipeline(transaction=False)
            for key in keys:
                pipe.hgetall(key)
            rows = pipe.execute() if keys else []
        except Exception as e:
            log.warning("Redis lookup failed (%s: %s); treating as a cache miss", type(e).__name__, e)
            return CacheResult(False, None, None, None, self.backend)
        best_sim, best = -1.0, None
        for row in rows:
            if not row:
                continue
            sim = float(np.frombuffer(row[b"vec"], dtype=np.float32) @ vec)
            if sim > best_sim:
                best_sim, best = sim, row
        if best is None:
            return CacheResult(False, None, None, None, self.backend)
        if best_sim >= self.threshold:
            return CacheResult(
                True, best_sim, best[b"query"].decode(), json.loads(best[b"value"]), self.backend
            )
        return CacheResult(False, best_sim, None, None, self.backend)

    def store(self, query: str, vec: np.ndarray, value: dict[str, Any]) -> None:
        key = f"{self.prefix}{time.time_ns()}"
        try:
            pipe = self.client.pipeline(transaction=False)
            pipe.hset(
                key,
                mapping={"query": query, "vec": vec.astype(np.float32).tobytes(), "value": json.dumps(value)},
            )
            pipe.expire(key, self.ttl_s)
            pipe.execute()
        except Exception as e:
            log.warning("Redis store failed (%s: %s); entry not cached", type(e).__name__, e)

    def clear(self) -> None:
        for key in self._keys():
            self.client.delete(key)

    def __len__(self) -> int:
        return len(self._keys())


def build_cache(settings, namespace: str, try_redis: bool = True) -> SemanticCache:
    """Redis if REDIS_URL is set and reachable (and `try_redis`), otherwise the in-memory fallback."""
    if settings.redis_url and try_redis:
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1.5, socket_timeout=1.5)
            return RedisSemanticCache(client, settings.cache_threshold, namespace)
        except Exception as e:
            log.warning("Redis unavailable (%s: %s); using the in-memory semantic cache", type(e).__name__, e)
    return MemorySemanticCache(settings.cache_threshold)
