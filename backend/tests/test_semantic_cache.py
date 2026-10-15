import fakeredis
import numpy as np
import pytest

from app.config import Settings
from app.rag.cache import MemorySemanticCache, RedisSemanticCache, build_cache


def _unit(*xs: float) -> np.ndarray:
    v = np.array(xs, dtype=np.float32)
    return v / np.linalg.norm(v)


def _vec_with_cosine(base: np.ndarray, cos: float) -> np.ndarray:
    """A unit vector whose cosine with `base` is exactly `cos` (base = e0)."""
    return _unit(cos, np.sqrt(1 - cos**2))


@pytest.fixture(params=["memory", "redis"])
def cache(request):
    if request.param == "memory":
        return MemorySemanticCache(0.92)
    return RedisSemanticCache(fakeredis.FakeRedis(), 0.92, namespace="t")


def test_empty_cache_misses(cache):
    r = cache.lookup(_unit(1, 0))
    assert not r.hit and r.similarity is None


def test_exact_repeat_hits(cache):
    cache.store("q", _unit(1, 0), {"answer": 1})
    r = cache.lookup(_unit(1, 0))
    assert r.hit and r.similarity == pytest.approx(1.0, abs=1e-5)
    assert r.value == {"answer": 1} and r.matched_query == "q"


def test_threshold_boundary(cache):
    base = _unit(1, 0)
    cache.store("q", base, {"a": 1})
    assert cache.lookup(_vec_with_cosine(base, 0.93)).hit
    assert cache.lookup(_vec_with_cosine(base, 0.925)).hit
    miss = cache.lookup(_vec_with_cosine(base, 0.90))
    assert not miss.hit and miss.similarity == pytest.approx(0.90, abs=1e-4)


def test_clear_and_len(cache):
    cache.store("q", _unit(1, 0), {})
    assert len(cache) == 1
    cache.clear()
    assert len(cache) == 0


def test_redis_entries_have_ttl():
    client = fakeredis.FakeRedis()
    c = RedisSemanticCache(client, 0.92, namespace="ttl", ttl_s=60)
    c.store("q", _unit(1, 0), {})
    key = next(iter(client.scan_iter("aegis:sc:ttl:*")))
    assert 0 < client.ttl(key) <= 60


def test_namespaces_are_isolated():
    client = fakeredis.FakeRedis()
    a = RedisSemanticCache(client, 0.92, namespace="v1")
    b = RedisSemanticCache(client, 0.92, namespace="v2")
    a.store("q", _unit(1, 0), {})
    assert not b.lookup(_unit(1, 0)).hit


def test_falls_back_to_memory_when_redis_unreachable():
    s = Settings(redis_url="redis://127.0.0.1:1/0")  # nothing listens on port 1
    assert build_cache(s, "ns").backend == "memory"


def test_no_redis_url_uses_memory():
    assert build_cache(Settings(redis_url=None), "ns").backend == "memory"


def test_redis_fallback_is_logged(caplog):
    with caplog.at_level("WARNING", logger="aegis.cache"):
        build_cache(Settings(redis_url="redis://127.0.0.1:1/0"), "ns")
    assert "using the in-memory semantic cache" in caplog.text
