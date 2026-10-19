"""Plain data types shared by the domain registry, calculators and answer checker."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PresetSpec:
    id: str
    kind: str  # hallucination_trap | tier1_router | prompt_injection
    title: str
    tagline: str
    query: str
    paraphrase: str | None
    card_kind: str


@dataclass(frozen=True)
class RequiredValue:
    label: str
    value: str  # numeric ("700.00") or text; "a|b" = any alternative
    unit: str = ""


@dataclass(frozen=True)
class ForbiddenPattern:
    label: str
    pattern: str  # regex


@dataclass(frozen=True)
class ExpectedAnswer:
    calculator: str
    required: tuple[RequiredValue, ...]
    forbidden: tuple[ForbiddenPattern, ...]
    details: dict[str, Any] = field(default_factory=dict)  # intermediate figures (tiers, totals, violations)


@dataclass
class VerdictResult:
    """Fields match VerdictData in frontend types.ts (minus the Common `side`)."""

    correct: bool
    required: list[dict[str, Any]]  # {label, expected, found}
    forbidden_hits: list[dict[str, Any]]  # {label, span: [start, end] | None}
    key_applies: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "correct": self.correct,
            "required": self.required,
            "forbidden_hits": self.forbidden_hits,
            "key_applies": self.key_applies,
        }
