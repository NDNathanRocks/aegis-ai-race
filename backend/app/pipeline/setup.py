"""Per-request race setup shared by both pipelines: domain runtime, preset, answer key, model allowlist."""
import dataclasses
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from app import domains as dom
from app.deps import AppContext
from app.llm.gateway import RaceRun
from app.presets import PRESETS
from app.schemas import RaceRequest, Tier


@dataclass
class RaceSetup:
    ctx: AppContext
    req: RaceRequest
    run: RaceRun
    runtime: dom.DomainRuntime
    preset: Any  # domains.PresetSpec | None
    expected: Any  # domains.ExpectedAnswer | None

    @property
    def kb_tokens(self) -> int:
        return self.runtime.spec.kb_tokens

    @property
    def preset_kind(self) -> str | None:
        return getattr(self.preset, "kind", None)

    def naive_tier(self) -> Tier:
        return "8b" if self.req.model_mode == "8b" else "70b"

    def model_for(self, tier: Tier) -> str:
        s = self.ctx.settings
        return s.groq_heavy_model if tier == "70b" else s.groq_fast_model

    def base_model(self) -> str:
        """The model the baseline (naive) side uses; `auto` baselines on the heavy model."""
        return self.model_for(self.naive_tier())

    def fallback_reason(self) -> str | None:
        return self.run.degraded_reason if self.run.degraded else self.run.reason

    def facts(self) -> Any:
        """Ground-truth facts that must appear in the retrieved context (drives Context Recall)."""
        facts = getattr(self.preset, "expected_facts", None)
        if not facts and self.preset is not None:
            legacy = PRESETS.get(self.preset.id)
            facts = legacy.expected_facts if legacy else None
        return SimpleNamespace(expected_facts=tuple(facts)) if facts else None


def make_setup(ctx: AppContext, req: RaceRequest, run: RaceRun) -> RaceSetup:
    preset = dom.get_preset(req.domain, req.preset_id)
    expected = None
    if preset is not None:
        # A paraphrase asks the same question, so it is scored by the hero's key.
        key_query = preset.query if (preset.paraphrase and req.query == preset.paraphrase) else req.query
        try:
            expected = dom.expected_answer(req.domain, preset.kind, key_query)
        except Exception:
            expected = None
    return RaceSetup(ctx, req, run, ctx.runtime(req.domain), preset, expected)


def verdict_dict(text_or_card: Any, expected: Any) -> dict[str, Any]:
    """Run the deterministic answer-key check; never raises. Shape == VerdictData minus Common."""
    if expected is None:
        return {"correct": False, "required": [], "forbidden_hits": [], "key_applies": False}
    try:
        v = dom.check_answer(text_or_card, expected)
        raw = v.model_dump() if hasattr(v, "model_dump") else dataclasses.asdict(v) if dataclasses.is_dataclass(v) else dict(v)
    except Exception:
        return {"correct": False, "required": [], "forbidden_hits": [], "key_applies": False}
    return {
        "correct": bool(raw.get("correct")),
        "required": [dict(r) for r in raw.get("required", [])],
        "forbidden_hits": [
            {"label": h.get("label"), "span": list(h["span"]) if h.get("span") else None}
            for h in raw.get("forbidden_hits", [])
        ],
        "key_applies": bool(raw.get("key_applies", True)),
    }


def expected_text(expected: Any) -> str:
    """Calculator-derived ground truth as text, so the Critic's numeric grounding accepts legitimately derived
    figures (e.g. 3 months x 1% x $4,500) that the two-step arithmetic check cannot reach on its own."""
    if expected is None:
        return ""
    return "\n".join(f"{r.label}: {r.value} {r.unit}".strip() for r in getattr(expected, "required", ()))
