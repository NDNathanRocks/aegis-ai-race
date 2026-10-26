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


def test_memory_cache_keeps_only_newest_entries():
    c = MemorySemanticCache(0.92, max_entries=3)
    for i in range(5):
        c.store(f"q{i}", _unit(1, i), {"i": i})
    assert len(c) == 3
    assert c.lookup(_unit(1, 0)).matched_query != "q0"  # oldest evicted


def test_memory_cache_concurrent_store_and_lookup():
    import threading

    c = MemorySemanticCache(0.92, max_entries=50)
    errors = []

    def writer():
        for i in range(2000):
            c.store("q", _unit(1, i % 7), {})

    def reader():
        try:
            for _ in range(2000):
                c.lookup(_unit(1, 0))
        except Exception as e:  # pragma: no cover - the regression this guards against
            errors.append(e)

    ts = [threading.Thread(target=writer), threading.Thread(target=reader), threading.Thread(target=reader)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors


def test_redis_errors_after_connect_degrade_to_miss(caplog):
    client = fakeredis.FakeRedis()
    c = RedisSemanticCache(client, 0.92, namespace="down")
    c.store("q", _unit(1, 0), {"v": 1})

    def broken(*a, **k):
        raise ConnectionError("redis went away")

    client.scan_iter = broken
    client.pipeline = broken
    with caplog.at_level("WARNING", logger="aegis.cache"):
        assert c.lookup(_unit(1, 0)).hit is False
        c.store("q2", _unit(0, 1), {})  # must not raise
    assert "treating as a cache miss" in caplog.text and "entry not cached" in caplog.text


def test_figures_match_normalises_formatting_but_not_values():
    from app.rag.cache import figures_match, query_figures

    assert query_figures("Billed $48,000 at 99.62% uptime") == ["48000", "99.62%"]
    assert figures_match("uptime drops to 99.7%?", "uptime came in at 99.7 percent")
    assert figures_match("$1,000.00 owed", "1000 owed")
    assert not figures_match("delayed 6.5 hours", "delayed 9.5 hours")
    assert not figures_match("a 6% increase", "a 6 month increase")
    assert not figures_match("1 passenger", "3 passengers")
    assert figures_match("no numbers here", "none here either")
