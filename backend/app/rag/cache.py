"""Semantic cache: Redis-backed with automatic in-memory NumPy fallback."""
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

log = logging.getLogger("aegis.cache")


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
    backend = "memory"

    def __init__(self, threshold: float = 0.92):
        self.threshold = threshold
        self._vecs: list[np.ndarray] = []
        self._entries: list[tuple[str, dict[str, Any]]] = []

    def lookup(self, vec: np.ndarray) -> CacheResult:
        if not self._vecs:
            return CacheResult(False, None, None, None, self.backend)
        sims = np.stack(self._vecs) @ vec
        i = int(np.argmax(sims))
        sim = float(sims[i])
        if sim >= self.threshold:
            q, v = self._entries[i]
            return CacheResult(True, sim, q, v, self.backend)
        return CacheResult(False, sim, None, None, self.backend)

    def store(self, query: str, vec: np.ndarray, value: dict[str, Any]) -> None:
        self._vecs.append(vec.astype(np.float32))
        self._entries.append((query, value))

    def clear(self) -> None:
        self._vecs.clear()
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


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
        best_sim, best = -1.0, None
        for key in self._keys():
            row = self.client.hgetall(key)
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
        self.client.hset(
            key,
            mapping={"query": query, "vec": vec.astype(np.float32).tobytes(), "value": json.dumps(value)},
        )
        self.client.expire(key, self.ttl_s)

    def clear(self) -> None:
        for key in self._keys():
            self.client.delete(key)

    def __len__(self) -> int:
        return len(self._keys())


def build_cache(settings, namespace: str) -> SemanticCache:
    """Redis if REDIS_URL is set and reachable, otherwise the in-memory fallback."""
    if settings.redis_url:
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1.5, socket_timeout=1.5)
            return RedisSemanticCache(client, settings.cache_threshold, namespace)
        except Exception as e:
            log.warning("Redis unavailable (%s: %s); using the in-memory semantic cache", type(e).__name__, e)
    return MemorySemanticCache(settings.cache_threshold)
