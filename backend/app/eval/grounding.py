"""Deterministic, offline grounding checks used by the Critic and the RAG-triad evaluator.

A numeric claim is *supported* if it appears in the context/query, or can be
derived from supported numbers by at most two arithmetic steps (sum/difference
of amounts, amount x percentage). Percentages must appear literally: a
percentage that is not in the source material is always a hallucination.
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

_NUM = re.compile(r"(?P<dollar>\$)?\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s?(?P<pct>%|percent)?")
_SKIP_KEYS = {"kind", "citations", "confidence", "priority", "invoice_id", "policy_clause", "suggested_queue"}
_STOP = frozenset(
    "a an the of to in on for and or is are be by with at as it this that from was were has have had not no "
    "your you we our their they its into than then so if but can may must will".split()
)
_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class Numbers:
    amounts: set[Decimal] = field(default_factory=set)
    percents: set[Decimal] = field(default_factory=set)


def extract_numbers(text: str) -> Numbers:
    out = Numbers()
    for m in _NUM.finditer(text):
        try:
            v = Decimal(m.group("num").replace(",", "").rstrip("."))
        except InvalidOperation:
            continue
        if m.group("pct"):
            out.percents.add(v)
        elif v >= 100 or m.group("dollar"):
            out.amounts.add(v)
    return out


def _derivable_set(base: Numbers) -> set[Decimal]:
    s1: set[Decimal] = set(base.amounts)
    amounts = list(base.amounts)
    for i, a in enumerate(amounts):
        for b in amounts[i + 1 :]:
            s1.add(a + b)
            s1.add(abs(a - b))
        for p in base.percents:
            s1.add((a * p / 100).quantize(Decimal(1)))
    return s1


def amount_supported(value: Decimal, base: Numbers, s1: set[Decimal] | None = None) -> bool:
    value = abs(value)
    s1 = s1 if s1 is not None else _derivable_set(base)
    if value in s1:
        return True
    return any((abs(value - a) in s1) or (value + a in s1) for a in s1)


@dataclass
class Grounding:
    faithfulness: float
    unsupported: list[str]
    claims_checked: int


def _walk(node: Any, key: str = "") -> list[tuple[str, Any]]:
    if isinstance(node, dict):
        return [x for k, v in node.items() for x in _walk(v, k)]
    if isinstance(node, list):
        return [x for v in node for x in _walk(v, key)]
    return [(key, node)]


def _content_tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 2}


def evaluate_grounding(payload: Any, context: str, query: str = "") -> Grounding:
    """Score how much of `payload` (str or parsed JSON) is supported by context + query."""
    leaves = _walk(payload) if not isinstance(payload, str) else [("", payload)]
    source = f"{context}\n{query}"
    base = extract_numbers(source)
    s1 = _derivable_set(base)
    source_tokens = _content_tokens(source)

    unsupported: list[str] = []
    checked = 0
    supported = 0

    for key, value in leaves:
        if key in _SKIP_KEYS or value is None or isinstance(value, bool):
            continue
        if isinstance(value, int | float | Decimal):
            nums = Numbers(amounts={Decimal(str(value))} if abs(Decimal(str(value))) >= 100 else set())
            text = str(value)
        else:
            text = str(value)
            nums = extract_numbers(text)
        for pct in nums.percents:
            checked += 1
            if pct in base.percents:
                supported += 1
            else:
                unsupported.append(f"{pct}% is not stated in the source documents")
        for amt in nums.amounts:
            checked += 1
            if amount_supported(amt, base, s1):
                supported += 1
            else:
                unsupported.append(f"${amt:,.0f} cannot be derived from the source documents")
        if isinstance(value, str) and len(value.split()) >= 5:
            toks = _content_tokens(re.sub(r"[\d$%,.]+", " ", value))
            if toks:
                checked += 1
                if len(toks & source_tokens) / len(toks) >= 0.5:
                    supported += 1
                else:
                    unsupported.append(f'Statement not grounded: "{value[:90]}"')

    faithfulness = 1.0 if checked == 0 else supported / checked
    return Grounding(round(faithfulness, 4), unsupported, checked)
