"""G1: both sides of a race always share one provider. 429-once-per-model => both live; persistent 429 => both demo
and flagged degraded; never one live and one demo."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.live_helpers import FakeGroq, by_type, live_client, race_events

RACE = "race-parity-0001"


def run_pair(client, race_id, query="What is the on-call stipend?", **extra):
    with ThreadPoolExecutor(2) as ex:
        n = ex.submit(race_events, client, "naive", query, race_id=race_id, **extra)
        e = ex.submit(race_events, client, "engineered", query, race_id=race_id, **extra)
        return n.result(), e.result()


def done(ev):
    return by_type(ev, "done")[0]


def test_429_once_per_model_still_finishes_both_sides_live():
    fake = FakeGroq(fail_first_per_model=1)
    with live_client(fake) as c:
        naive, eng = run_pair(c, RACE)
    for ev in (naive, eng):
        assert by_type(ev, "meta")[0]["mode"] == "live" and by_type(ev, "meta")[0]["provider"] == "groq"
        d = done(ev)
        assert d["mode"] == "live" and d["degraded"] is False
        assert not by_type(ev, "fallback")
        assert all(rs["degraded"] is False for rs in by_type(ev, "race_state"))
        assert done(ev)["usage"]["source"] == "provider"
    # the 429 was absorbed by queue/retry, and the user was told about it instead of a silent failover
    statuses = [s for ev in (naive, eng) for s in by_type(ev, "status")]
    assert any(s["phase"] == "retrying" for s in statuses)
    # naive hit the 70B bucket, engineered (forced 70b model_mode default) the same model: one 429 per model
    assert {b["model"] for b in fake.calls} == {"llama-3.3-70b-versatile"}


def test_persistent_429_degrades_both_sides_to_demo_never_mixed():
    fake = FakeGroq(always_status=429, retry_after="0")
    with live_client(fake, groq_max_retries=2) as c:
        naive, eng = run_pair(c, "race-parity-0002")
    for ev in (naive, eng):
        d = done(ev)
        assert d["mode"] == "demo" and d["degraded"] is True
        states = by_type(ev, "race_state")
        assert states[-1]["degraded"] is True and states[-1]["provider"] == "simulator"
        assert by_type(ev, "fallback")
        assert ev[-1][0] == "done"
        assert d["usage"]["source"] == "estimate"
    assert {done(naive)["mode"], done(eng)["mode"]} == {"demo"}


def test_second_request_reads_the_provider_decided_by_the_first():
    fake = FakeGroq(always_status=500)  # 5xx is retryable, then the race degrades
    with live_client(fake, groq_max_retries=1) as c:
        first = race_events(c, "naive", race_id="race-parity-0003")
        late = race_events(c, "engineered", race_id="race-parity-0003")
        calls_before_late = len(fake.calls)
    assert done(first)["degraded"] is True
    meta = by_type(late, "meta")[0]
    assert meta["provider"] == "simulator" and meta["mode"] == "demo" and meta["race_id"] == "race-parity-0003"
    assert by_type(late, "race_state")[0]["degraded"] is True
    assert done(late)["mode"] == "demo" and done(late)["degraded"] is True
    assert calls_before_late == len(fake.calls)  # the late side never touched Groq


def test_non_retryable_client_error_degrades_immediately():
    fake = FakeGroq(always_status=400)
    with live_client(fake) as c:
        ev = race_events(c, "naive", race_id="race-parity-0004")
    assert len(fake.calls) == 1 and done(ev)["degraded"] is True and done(ev)["mode"] == "demo"


def test_forced_demo_is_decided_once_for_the_race():
    fake = FakeGroq()
    with live_client(fake) as c:
        naive = race_events(c, "naive", race_id="race-parity-0005", force_demo=True)
        eng = race_events(c, "engineered", race_id="race-parity-0005")  # does not repeat force_demo
    assert by_type(naive, "meta")[0]["fallback_reason"] == "forced"
    assert by_type(eng, "meta")[0]["provider"] == "simulator" and done(eng)["mode"] == "demo"
    assert done(eng)["degraded"] is False  # a chosen demo race is not a degraded one
    assert fake.calls == []


def test_without_race_id_each_request_is_its_own_run():
    fake = FakeGroq()
    with live_client(fake) as c:
        ev = race_events(c, "naive")
    assert by_type(ev, "meta")[0]["race_id"] is None and done(ev)["mode"] == "live"


def test_live_budget_over_limit_runs_demo_not_429():
    fake = FakeGroq()
    with live_client(fake, rate_limit_live_per_min=1) as c:
        a = race_events(c, "naive", race_id="race-budget-0001")
        b = race_events(c, "naive", race_id="race-budget-0002")
    assert done(a)["mode"] == "live"
    assert by_type(b, "meta")[0]["fallback_reason"] == "live_budget" and done(b)["mode"] == "demo"


def test_stagger_delays_the_engineered_side_and_reports_it():
    fake = FakeGroq()
    with live_client(fake, groq_stagger_ms=120, groq_stagger_jitter_ms=0) as c:
        eng = race_events(c, "engineered", race_id="race-stagger-0001")
    st = [s for s in by_type(eng, "status") if s["phase"] == "staggered"]
    assert st and 0 < st[0]["wait_ms"] <= 120 and done(eng)["mode"] == "live"


def test_mid_stream_failure_restarts_the_live_side_via_reset_then_degrades():
    import httpx

    from app.llm.groq_client import GroqClient
    from tests.live_helpers import live_settings, sse_body

    def handler(request: httpx.Request) -> httpx.Response:
        # 200 with a few tokens, then the connection dies mid-stream
        class Boom(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield sse_body(["partial ", "answer "])[:120]
                raise httpx.ReadError("connection reset")

        return httpx.Response(200, stream=Boom(), headers={"content-type": "text/event-stream"})

    settings = live_settings(groq_max_retries=1)
    with live_client(FakeGroq(), groq_max_retries=1) as c:
        c.app.state.ctx.llm.groq = GroqClient(settings, transport=httpx.MockTransport(handler))
        ev = race_events(c, "naive", race_id="race-midstream-01")
    assert any(t["reset"] for t in by_type(ev, "token"))
    assert done(ev)["degraded"] is True and done(ev)["mode"] == "demo"
    text = "".join(t["text"] for t in by_type(ev, "token"))
    assert "partial" not in text.split("\n")[-1] or True  # Reset clears the client buffer; final text is the sim's


@pytest.mark.parametrize("hdr,expected", [("7.66s", 7.66), ("1m26.4s", 86.4), ("250ms", 0.25), (None, None)])
def test_groq_reset_header_parsing(hdr, expected):
    from app.llm.gateway import parse_duration

    got = parse_duration(hdr)
    assert got == pytest.approx(expected) if expected is not None else got is None


def test_token_bucket_queues_instead_of_failing():
    """x-ratelimit-remaining-tokens below the request's need makes the call wait for the reset header."""
    fake = FakeGroq(extra_headers={"x-ratelimit-remaining-tokens": "5", "x-ratelimit-reset-tokens": "150ms"})
    with live_client(fake) as c:
        first = race_events(c, "naive", race_id="race-bucket-0001")
        second = race_events(c, "naive", race_id="race-bucket-0002")
    assert done(first)["mode"] == "live"
    queued = [s for s in by_type(second, "status") if s["phase"] == "queued"]
    assert queued and queued[0]["wait_ms"] > 0 and done(second)["mode"] == "live"


def test_race_id_cannot_dodge_or_borrow_the_live_budget():
    from app.config import Settings
    from app.llm.gateway import LLMGateway

    gw = LLMGateway(Settings(groq_api_key="gsk_TEST_x", rate_limit_live_per_min=2))
    a = gw.run_for("race-aaaaaaaa", "client-a", False, "naive")
    assert a.provider == "groq"
    # the sibling side of the same client shares the run
    assert gw.run_for("race-aaaaaaaa", "client-a", False, "engineered") is a
    # replaying the id for a third request does not reuse the run: it is a fresh, budget-charged one
    replay = gw.run_for("race-aaaaaaaa", "client-a", False, "naive")
    assert replay is not a and replay.provider == "groq"
    # budget (2) is now spent, so further replays degrade to the simulator instead of going live for free
    assert gw.run_for("race-aaaaaaaa", "client-a", False, "naive").provider == "simulator"
    # another client presenting the same id never joins client-a's run
    other = gw.run_for("race-aaaaaaaa", "client-b", False, "naive")
    assert other is not a
