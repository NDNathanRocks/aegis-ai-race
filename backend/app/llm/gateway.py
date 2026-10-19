"""RaceRun registry + LLMGateway: the single place that decides provider and enforces Groq parity.

One RaceRun per race_id. The provider ("groq" | "simulator") is decided ONCE, by whichever side arrives first.
If Groq cannot be reached after the retry budget the whole run flips to `degraded`: BOTH sides finish in
simulator mode (a side that is mid-stream live is restarted via `Reset`). We never silently leave one side live
and the other demo.
"""
import asyncio
import inspect
import random
import re
import time
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from app.config import Settings
from app.cost import estimate_tokens
from app.llm.base import (
    LLMRequest,
    LLMUnavailable,
    RaceStateChange,
    Reset,
    Status,
    Usage,
    build_messages,
)
from app.llm.groq_client import GroqClient
from app.llm.simulator import SimulatorClient

Provider = Literal["groq", "simulator"]
Item = str | Reset | Usage | Status | RaceStateChange

_DUR = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_UNIT = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_duration(text: str | None) -> float | None:
    """Groq reset headers look like '7.66s', '1m26.4s', '250ms'."""
    if not text:
        return None
    parts = _DUR.findall(text)
    if not parts:
        try:
            return float(text)
        except ValueError:
            return None
    return sum(float(n) * _UNIT[u] for n, u in parts)


@dataclass
class ModelState:
    """Per-model limiter derived from Groq's own headers. Never sticky beyond what the headers say."""

    blocked_until: float = 0.0  # monotonic; set from retry-after on a 429
    remaining_tokens: int | None = None
    reset_at: float = 0.0

    def observe(self, headers: dict[str, str], now: float) -> None:
        rem = headers.get("x-ratelimit-remaining-tokens")
        reset = parse_duration(headers.get("x-ratelimit-reset-tokens"))
        if rem is not None:
            try:
                self.remaining_tokens = int(float(rem))
                self.reset_at = now + (reset or 0.0)
            except ValueError:
                pass

    def wait_for(self, need: int, now: float) -> float:
        """Seconds to queue before `need` tokens fit in the bucket (0 when unknown or available)."""
        wait = max(0.0, self.blocked_until - now)
        if self.remaining_tokens is not None:
            if now >= self.reset_at:
                self.remaining_tokens = None  # the bucket has refilled; forget stale info
            elif self.remaining_tokens < need:
                wait = max(wait, self.reset_at - now)
        return wait

    def reserve(self, need: int) -> None:
        if self.remaining_tokens is not None:
            self.remaining_tokens = max(0, self.remaining_tokens - need)


@dataclass
class RaceRun:
    race_id: str | None
    provider: Provider
    reason: str | None  # why the provider is the simulator (no_key | forced | live_budget), None when live
    sem: asyncio.Semaphore
    created: float = field(default_factory=time.monotonic)
    degraded: bool = False
    degraded_reason: str | None = None
    _notified: set[str] = field(default_factory=set)

    def degrade(self, reason: str) -> None:
        if not self.degraded:
            self.degraded, self.degraded_reason = True, reason
            self.provider = "simulator"

    def take_notification(self, side: str) -> bool:
        """True exactly once per side: whether this side still owes the client a degraded race_state event."""
        if side in self._notified:
            return False
        self._notified.add(side)
        return True

    @property
    def mode(self) -> Literal["live", "demo"]:
        return "live" if self.provider == "groq" else "demo"

    def state_event(self) -> RaceStateChange:
        return RaceStateChange(self.degraded, self.degraded_reason, self.provider)


class LiveBudget:
    """Per-client sliding window of live races. Over budget -> the race runs in demo mode (nothing is rejected)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = {}

    def take(self, key: str) -> bool:
        now = time.monotonic()
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        if len(self._hits) > 5000:
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 60]:
                del self._hits[k]
        return True


def _accepts_headers(groq) -> bool:
    try:
        return "on_headers" in inspect.signature(groq.stream).parameters
    except (TypeError, ValueError):
        return False


class LLMGateway:
    def __init__(self, settings: Settings, groq: GroqClient | None = None, sim: SimulatorClient | None = None):
        self.settings = settings
        self.groq = groq or GroqClient(settings)
        self.sim = sim or SimulatorClient(settings.sim_time_scale)
        self._runs: OrderedDict[str, RaceRun] = OrderedDict()
        self._models: dict[str, ModelState] = {}
        self._budget = LiveBudget(settings.rate_limit_live_per_min)

    # ---- provider decision ------------------------------------------------------------------------
    def mode(self, force_demo: bool = False) -> tuple[str, str | None]:
        """Race-less view for /api/config and tests: is live mode possible at all?"""
        if force_demo or self.settings.force_demo:
            return "demo", "forced"
        if not self.settings.groq_api_key:
            return "demo", "no_key"
        return "live", None

    def run_for(self, race_id: str | None, client_key: str = "anon", force_demo: bool = False) -> RaceRun:
        """Return the RaceRun for `race_id`, creating it (and deciding the provider) on first use."""
        now = time.monotonic()
        for rid in [r for r, run in self._runs.items() if now - run.created > self.settings.race_ttl_s]:
            del self._runs[rid]
        if race_id and race_id in self._runs:
            return self._runs[race_id]
        mode, reason = self.mode(force_demo)
        if mode == "live" and not self._budget.take(client_key):
            mode, reason = "demo", "live_budget"
        run = RaceRun(
            race_id=race_id,
            provider="groq" if mode == "live" else "simulator",
            reason=reason,
            sem=asyncio.Semaphore(self.settings.groq_concurrency),
        )
        if race_id:
            self._runs[race_id] = run
            while len(self._runs) > self.settings.race_registry_max:
                self._runs.popitem(last=False)
        return run

    # ---- limiter ------------------------------------------------------------------------------------
    def _state(self, model: str) -> ModelState:
        return self._models.setdefault(model, ModelState())

    def _observe(self, model: str, headers: dict[str, str]) -> None:
        self._state(model).observe(headers, time.monotonic())

    def model_name(self, req: LLMRequest) -> str:
        fn = getattr(self.groq, "model_for", None)
        if fn:
            return fn(req)
        return self.settings.groq_heavy_model if req.tier == "70b" else self.settings.groq_fast_model

    # ---- streaming ----------------------------------------------------------------------------------
    async def _sim_stream(self, req: LLMRequest) -> AsyncIterator[str | Usage]:
        text = ""
        async for piece in self.sim.stream(req):
            if isinstance(piece, str):
                text += piece
                yield piece
        prompt = sum(estimate_tokens(m["content"]) for m in build_messages(req))
        yield Usage(prompt, estimate_tokens(text), self.model_name(req), "estimate")

    async def _degraded_tail(self, run: RaceRun, req: LLMRequest, started: bool) -> AsyncIterator[Item]:
        if req.on_fallback:
            req.on_fallback(run.degraded_reason or "upstream_error")
        if run.take_notification(req.side):
            yield run.state_event()
        if started:
            yield Reset()
        async for x in self._sim_stream(req):
            yield x

    async def stream(self, run: RaceRun, req: LLMRequest) -> AsyncIterator[Item]:
        s = self.settings
        if run.degraded:
            async for x in self._degraded_tail(run, req, started=False):
                yield x
            return
        if run.provider != "groq":
            async for x in self._sim_stream(req):
                yield x
            return

        # Stagger: the engineered side's first Groq call trails the naive side by ~150 ms so they do not hit the
        # TPM bucket in the same instant. Only the shortfall since the race began is waited.
        if req.role == "generator" and req.attempt == 0:
            jitter = s.groq_stagger_jitter_ms
            target = (s.groq_stagger_ms + random.uniform(-jitter, jitter)) / 1000
            wait = target - (time.monotonic() - run.created)
            if wait > 0.005:
                yield Status("staggered", "Started a beat behind the baseline to share Groq's rate bucket", int(wait * 1000))
                await asyncio.sleep(wait)

        model = self.model_name(req)
        need = sum(estimate_tokens(m["content"]) for m in build_messages(req)) + 250
        t0 = time.monotonic()
        attempt = 0
        started = False
        while True:
            if run.degraded:
                async for x in self._degraded_tail(run, req, started):
                    yield x
                return
            state = self._state(model)
            wait = state.wait_for(need, time.monotonic())
            if wait > 0:
                if time.monotonic() - t0 + wait > s.groq_retry_budget_s:
                    run.degrade("rate_limited")
                    continue
                yield Status("queued", f"Queued for Groq token budget ({model})", int(wait * 1000))
                await asyncio.sleep(wait)
                continue
            state.reserve(need)
            err: LLMUnavailable | None = None
            inner = None
            finished = False
            try:
                async with run.sem:
                    if _accepts_headers(self.groq):
                        inner = self.groq.stream(req, on_headers=self._observe)
                    else:
                        inner = self.groq.stream(req)
                    async for item in inner:
                        if run.degraded:  # the sibling side gave up while we were mid-stream
                            break
                        if isinstance(item, str):
                            started = True
                        yield item
                    else:
                        finished = True
            except LLMUnavailable as e:
                err = e
            finally:
                aclose = getattr(inner, "aclose", None)
                if aclose:
                    await aclose()
            if finished:
                return
            if err is None:  # broke out because the run degraded
                continue
            if err.headers:
                self._observe(model, err.headers)
            wait = max(s.groq_backoff_base_s * (2**attempt), err.retry_after or 0.0)
            if err.reason == "rate_limited":
                state.blocked_until = max(state.blocked_until, time.monotonic() + wait)
            elapsed = time.monotonic() - t0
            if not err.retryable or attempt >= s.groq_max_retries or elapsed + wait > s.groq_retry_budget_s:
                run.degrade(err.reason)
                continue
            if started:
                yield Reset()
                started = False
            reason = err.reason.replace("_", " ")
            yield Status("retrying", f"Groq {reason}; retry {attempt + 1} in {wait:.1f}s", int(wait * 1000))
            attempt += 1
            await asyncio.sleep(wait)
