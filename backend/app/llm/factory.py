"""ResilientLLM: Groq when available, otherwise (or on failure) the deterministic simulator."""
import time
from collections.abc import AsyncIterator

from app.config import Settings
from app.llm.base import LLMRequest, LLMUnavailable, Reset
from app.llm.groq_client import GroqClient
from app.llm.simulator import SimulatorClient

COOLDOWN_S = 60.0


class ResilientLLM:
    def __init__(self, settings: Settings, groq: GroqClient | None = None, sim: SimulatorClient | None = None):
        self.settings = settings
        self.groq = groq or GroqClient(settings)
        self.sim = sim or SimulatorClient(settings.sim_time_scale)
        self._cooldown_until = 0.0
        self._cooldown_reason: str | None = None

    def mode(self, force_demo: bool = False) -> tuple[str, str | None]:
        """(mode, fallback_reason) for a run that is about to start."""
        if force_demo or self.settings.force_demo:
            return "demo", "forced"
        if not self.settings.groq_api_key:
            return "demo", "no_key"
        if time.monotonic() < self._cooldown_until:
            return "demo", self._cooldown_reason
        return "live", None

    async def stream(self, req: LLMRequest, force_demo: bool = False) -> AsyncIterator[str | Reset]:
        mode, _ = self.mode(force_demo)
        if mode == "demo":
            async for t in self.sim.stream(req):
                yield t
            return
        started = False
        try:
            async for t in self.groq.stream(req):
                started = True
                yield t
            return
        except LLMUnavailable as e:
            self._cooldown_until = time.monotonic() + COOLDOWN_S
            self._cooldown_reason = e.reason
            if req.on_fallback:
                req.on_fallback(e.reason)
        if started:
            yield Reset()
        async for t in self.sim.stream(req):
            yield t
