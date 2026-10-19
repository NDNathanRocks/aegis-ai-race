"""Northwind Master SLA invoice audit calculator (current v3.2 tiers)."""
from decimal import ROUND_HALF_UP, Decimal

from ._parse import first_num
from .types import ExpectedAnswer, ForbiddenPattern, RequiredValue

# (uptime lower bound inclusive, upper bound exclusive, credit percent) -- SLA Section 3
CREDIT_TIERS = [
    (Decimal("99.9"), Decimal("99.95"), Decimal(10)),
    (Decimal("99.0"), Decimal("99.9"), Decimal(25)),
    (Decimal("0"), Decimal("99.0"), Decimal(50)),
]
COMMITMENT = Decimal("99.95")


def credit_percent(uptime: Decimal) -> Decimal:
    if uptime >= COMMITMENT:
        return Decimal(0)
    for lo, hi, pct in CREDIT_TIERS:
        if lo <= uptime < hi:
            return pct
    return Decimal(0)


def audit(fee: Decimal, uptime: Decimal, billed_total: Decimal) -> dict:
    pct = credit_percent(uptime)
    credit = (fee * pct / 100).quantize(Decimal(1), ROUND_HALF_UP)
    expected_total = fee - credit  # Premium Support is included in the Enterprise Plan: not billable
    return {
        "credit_pct": pct, "credit": credit, "expected_total": expected_total,
        "billed_total": billed_total, "overbilled": billed_total - expected_total,
    }


def expected(query: str, key: dict) -> ExpectedAnswer | None:
    fee = first_num(r"billed\s+\$\s?([\d,]+(?:\.\d+)?)", query)
    uptime = first_num(r"(\d{2}(?:\.\d+)?)\s*%\s*(?:monthly\s+)?uptime", query)
    if fee is None or uptime is None:
        return None
    billed = first_num(r"total(?:ing|ling)?\s+\$\s?([\d,]+(?:\.\d+)?)", query)
    if billed is None:
        applied = first_num(r"\(\s*-\s*\$\s?([\d,]+(?:\.\d+)?)\s*\)", query) or Decimal(0)
        premium = first_num(r"\$\s?([\d,]+(?:\.\d+)?)\s+for\s+24x7\s+premium", query) or Decimal(0)
        billed = fee - applied + premium
    a = audit(fee, uptime, billed)
    req = [RequiredValue("Approved payout", str(a["expected_total"]), "USD")]
    if a["overbilled"] != 0:
        req.append(RequiredValue("Overbilled amount", str(abs(a["overbilled"])), "USD"))
    forb = tuple(ForbiddenPattern(f["label"], f["pattern"]) for f in key.get("forbidden", []))
    return ExpectedAnswer("invoice", tuple(req), forb, {k: str(v) for k, v in a.items()})
