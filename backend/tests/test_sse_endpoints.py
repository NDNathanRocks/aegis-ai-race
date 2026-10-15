import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import sse as sse_mod
from app.config import Settings
from app.main import create_app
from app.presets import PRESETS
from tests.conftest import parse_sse

from .test_llm import _FailAfter


def hashing_settings(**kw) -> Settings:
    base = dict(groq_api_key=None, redis_url=None, database_url=None, embedding_backend="hashing", sim_time_scale=0.0,
                rate_limit_per_min=10_000)
    return Settings(**{**base, **kw})


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(hashing_settings())) as c:
        yield c


def race(client, side, query="What is the on-call stipend?", **extra):
    with client.stream("POST", f"/api/race/{side}", json={"query": query, **extra}) as r:
        return r, parse_sse(r)


# --- REST -----------------------------------------------------------------------------------------
def test_health_config_presets(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    cfg = client.get("/api/config").json()
    assert cfg["mode"] == "demo" and cfg["cache_backend"] == "memory" and cfg["cache_threshold"] == 0.92
    presets = client.get("/api/presets").json()
    assert [p["id"] for p in presets] == list(PRESETS)
    assert "wrong_markers" not in presets[0]  # ground truth stays server-side


def test_knowledge_base_drawer_endpoints(client):
    docs = client.get("/api/kb/documents").json()
    assert len(docs) == 6
    full = client.get(f"/api/kb/documents/{docs[0]['id']}").json()
    assert full["text"].startswith("# ")
    assert client.get("/api/kb/documents/nope").status_code == 404
    assert client.get("/api/kb/documents/..%2F..%2Fsecrets").status_code == 404


def test_cache_reset(client):
    assert client.post("/api/cache/reset", json={"session_id": "abc"}).json() == {"ok": True}


# --- validation, CORS, rate limit ---------------------------------------------------------------------
@pytest.mark.parametrize("body", [{}, {"query": ""}, {"query": "x" * 2001}, {"query": "ok", "preset_id": "bogus"}])
def test_invalid_bodies_are_rejected(client, body):
    assert client.post("/api/race/naive", json=body).status_code == 422


def test_unknown_side_is_rejected(client):
    assert client.post("/api/race/sideways", json={"query": "hi"}).status_code == 422


def test_cors_allows_configured_origin_only(client):
    ok = client.options("/api/race/naive", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    bad = client.options("/api/race/naive", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers
    with client.stream("POST", "/api/race/naive", json={"query": "hi"}, headers={"Origin": "http://localhost:3000"}) as s:
        assert s.headers["access-control-allow-origin"] == "http://localhost:3000"
        list(s.iter_lines())


def test_rate_limit_returns_429_with_retry_after():
    with TestClient(create_app(hashing_settings(rate_limit_per_min=2))) as c:
        assert c.post("/api/race/naive", json={"query": "a b c"}).status_code == 200
        assert c.post("/api/race/naive", json={"query": "a b c"}).status_code == 200
        r = c.post("/api/race/naive", json={"query": "a b c"})
        assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


# --- stream contract ----------------------------------------------------------------------------------
@pytest.mark.parametrize("side", ["naive", "engineered"])
def test_stream_headers_and_envelope(client, side):
    r, ev = race(client, side)
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["x-accel-buffering"] == "no" and "no-transform" in r.headers["cache-control"]
    assert ev[0][0] == "meta" and ev[-1][0] == "done"
    run_ids = {d["run_id"] for _, d in ev}
    assert len(run_ids) == 1 and {d["side"] for _, d in ev} == {side}
    t = [d["t_ms"] for _, d in ev]
    assert t == sorted(t)  # server clock never goes backwards
    assert ev[0][1]["mode"] == "demo" and ev[0][1]["fallback_reason"] == "no_key"


def test_token_events_carry_running_totals(client):
    _, ev = race(client, "naive", PRESETS["semantic_cache"].query, preset_id="semantic_cache")
    toks = [d for e, d in ev if e == "token"]
    assert toks and toks[-1]["completion_tokens"] >= toks[0]["completion_tokens"] > 0
    assert toks[-1]["cost_usd"] > 0
    final = [d for e, d in ev if e == "done"][0]["usage"]
    assert final["completion_tokens"] == toks[-1]["completion_tokens"]


def test_concurrent_race_streams_do_not_interfere(client):
    p = PRESETS["tier1_triage"]

    def go(side):
        _, ev = race(client, side, p.query, preset_id=p.id, session_id=f"c-{side}")
        return side, ev

    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(go, ["naive", "engineered"] * 3))
    for side, ev in results:
        assert ev[-1][0] == "done" and {d["side"] for _, d in ev} == {side}
    assert len({ev[0][1]["run_id"] for _, ev in results}) == 6


# --- resilience ---------------------------------------------------------------------------------------
def test_live_failure_mid_stream_emits_fallback_and_still_completes():
    with TestClient(create_app(hashing_settings(groq_api_key="k"))) as c:
        c.app.state.ctx.llm.groq = _FailAfter(2, "rate_limited")
        _, ev = race(c, "naive", "anything at all")
        names = [e for e, _ in ev]
        assert ev[0][1]["mode"] == "live"
        fb = [d for e, d in ev if e == "fallback"]
        assert fb == [{**fb[0]}] and fb[0]["reason"] == "rate_limited" and fb[0]["switched_to"] == "demo"
        assert any(d["reset"] for e, d in ev if e == "token")
        assert names[-1] == "done" and ev[-1][1]["mode"] == "demo"


def test_internal_failure_yields_terminal_error_event(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("index exploded")

    monkeypatch.setattr(client.app.state.ctx.retriever, "retrieve", boom)
    _, ev = race(client, "engineered", "What is the on-call stipend?", session_id="boom-session")
    assert ev[-1][0] == "error" and ev[-1][1]["code"] == "internal_error" and "index exploded" in ev[-1][1]["message"]


# --- sse_stream unit tests --------------------------------------------------------------------------------
async def test_heartbeat_is_sent_while_idle(monkeypatch):
    monkeypatch.setattr(sse_mod, "HEARTBEAT_S", 0.02)
    em = sse_mod.Emitter("naive")

    async def slow():
        await asyncio.sleep(0.1)
        yield em.event("done", total_ms=1)

    frames = [f async for f in sse_mod.sse_stream(slow(), em)]
    assert ": ping\n\n" in frames and frames[-1].startswith("event: done")


async def test_stream_without_terminal_event_gets_an_error_frame():
    em = sse_mod.Emitter("naive")

    async def partial():
        yield em.event("meta")

    frames = [f async for f in sse_mod.sse_stream(partial(), em)]
    assert frames[-1].startswith("event: error") and "no_terminal_event" in frames[-1]


async def test_client_disconnect_closes_the_source_generator():
    em = sse_mod.Emitter("naive")
    closed = asyncio.Event()

    async def source():
        try:
            yield em.event("meta")
            await asyncio.sleep(30)
        finally:
            closed.set()

    stream = sse_mod.sse_stream(source(), em)
    assert (await stream.__anext__()).startswith("event: meta")
    await stream.aclose()  # what Starlette does when the client goes away
    assert closed.is_set()
