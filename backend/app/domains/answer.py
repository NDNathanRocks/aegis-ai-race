"""Deterministic answer-key check: required values found, forbidden patterns hit. Pure Python, no LLM judge."""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .types import ExpectedAnswer, VerdictResult

_NUMERIC = re.compile(r"^-?\d[\d,]*(\.\d+)?$")
# A forbidden phrase directly preceded by a negation/contrast cue ("not the EUR 600", "rather than 3.0%") is a
# rebuttal, not an assertion, so it is not reported as a hit.
_NEGATION_BEFORE = re.compile(
    r"(?:\bnot|n't|\bthan|\binstead of|\bwithout|\bno|\bnever)\s+(?:the\s+|a\s+|an\s+|any\s+|that\s+)?"
    r"(?:about\s+|approximately\s+)?(?:[\"'“‘(]\s*)?$",
    re.I,
)
# A mention inside a sentence that dismisses it ("... is irrelevant", "EU 261 does not apply") is a rebuttal too.
_DISMISSAL = re.compile(
    r"\b(?:irrelevant|(?:does|do|did)\s+not\s+(?:apply|entitle|qualify)|(?:doesn't|don't|didn't)\s+(?:apply|entitle|qualify)"
    r"|not\s+(?:applicable|entitled|eligible|valid)|inapplicable|incorrect(?:ly)?|wrong(?:ly)?|mistaken|misleading|myth"
    r"|invalid|superseded|outdated|rather\s+than|instead\s+of|ignore[sd]?|disregard\w*)\b",
    re.I,
)
_SENTENCE_BREAK = re.compile(r"\n|(?<=[A-Za-z)*'\u2019])[.!?]\s")
# Model output often carries typographic characters; map them 1:1 so match offsets stay valid for the original text.
_PLAIN = str.maketrans({
    "\u00a0": " ", "\u2007": " ", "\u2009": " ", "\u202f": " ", "\u200b": " ",
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2212": "-", "\u2019": "'", "\u2018": "'",
})


def _plain_text(text: str) -> str:
    return text.translate(_PLAIN)


def _sentence_around(text: str, start: int, end: int) -> str:
    left = max((m.end() for m in _SENTENCE_BREAK.finditer(text, max(0, start - 300), start)), default=max(0, start - 300))
    nxt = _SENTENCE_BREAK.search(text, end, end + 300)
    return text[left : nxt.start() if nxt else min(len(text), end + 300)]


# Card keys whose text restates claims in order to reject them; excluded when scanning a card for forbidden patterns.
_REBUTTAL_KEYS = re.compile(r"reject|dismiss|distractor|supersed|citation", re.I)


def _strip_rebuttals(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_rebuttals(v) for k, v in obj.items() if not _REBUTTAL_KEYS.search(str(k))}
    if isinstance(obj, list):
        return [_strip_rebuttals(v) for v in obj]
    return obj


def _as_plain(card: Any) -> Any:
    if hasattr(card, "model_dump"):
        return card.model_dump(mode="json")
    return card


def number_pattern(value: str) -> str:
    """Regex matching `value` as a standalone number: optional $, thousands commas and trailing zeros tolerated."""
    try:
        d = Decimal(value.replace(",", ""))
    except InvalidOperation:  # pragma: no cover - guarded by _NUMERIC
        return re.escape(value)
    text = format(d.normalize(), "f")
    whole, _, frac = text.partition(".")
    whole = whole.lstrip("-")
    if len(whole) > 3:
        groups: list[str] = []
        w = whole
        while w:
            groups.append(w[-3:])
            w = w[:-3]
        commaed = ",".join(reversed(groups))
        whole_pat = f"(?:{re.escape(commaed)}|{re.escape(whole)})"
    else:
        whole_pat = re.escape(whole)
    frac_pat = rf"\.{frac}0*" if frac else r"(?:\.0+)?"
    return rf"(?<![\d.,]){whole_pat}{frac_pat}(?!\d)(?!\.\d)(?!,\d)"


def _alt_pattern(alt: str) -> str:
    alt = alt.strip()
    if _NUMERIC.match(alt):
        return number_pattern(alt)
    return rf"(?<![A-Za-z0-9]){re.escape(alt)}(?![A-Za-z0-9])"


def value_found(expected_value: str, text: str) -> bool:
    text = _plain_text(text)
    return any(re.search(_alt_pattern(a), text, re.I) for a in expected_value.split("|") if a.strip())


def _first_asserted_match(pattern: str, text: str) -> tuple[int, int] | None:
    text = _plain_text(text)
    for m in re.finditer(pattern, text, re.I):
        if _NEGATION_BEFORE.search(text[max(0, m.start() - 40) : m.start()]):
            continue
        if _DISMISSAL.search(_sentence_around(text, m.start(), m.end())):
            continue
        return m.start(), m.end()
    return None


def check_answer(text_or_card: Any, expected: ExpectedAnswer | None) -> VerdictResult:
    """Score a final answer (free text or a card dict/model) against an ExpectedAnswer.

    `expected is None` means the key does not apply (e.g. the prompt was edited): key_applies=False."""
    if expected is None:
        return VerdictResult(correct=False, required=[], forbidden_hits=[], key_applies=False)

    is_card = not isinstance(text_or_card, str)
    if is_card:
        plain = _as_plain(text_or_card)
        full = json.dumps(plain, ensure_ascii=False)
        scan = json.dumps(_strip_rebuttals(plain), ensure_ascii=False)
    else:
        full = scan = text_or_card

    required = [
        {"label": r.label, "expected": f"{r.value} {r.unit}".strip(), "found": value_found(r.value, full)}
        for r in expected.required
    ]
    hits = []
    for f in expected.forbidden:
        span = _first_asserted_match(f.pattern, scan)
        if span is not None:
            hits.append({"label": f.label, "span": None if is_card else [span[0], span[1]]})
    correct = all(r["found"] for r in required) and not hits
    return VerdictResult(correct=correct, required=required, forbidden_hits=hits, key_applies=True)
