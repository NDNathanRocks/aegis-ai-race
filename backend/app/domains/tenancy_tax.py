"""BC rent-increase cap and CRA TFSA over-contribution penalty calculator."""
from decimal import ROUND_HALF_UP, Decimal

from ._parse import CENT, first_num, money
from .types import ExpectedAnswer, ForbiddenPattern, RequiredValue

BC_CAP_2026 = Decimal("0.023")
TFSA_MONTHLY_RATE = Decimal("0.01")


def rent_cap(rent: Decimal, cap: Decimal = BC_CAP_2026) -> dict:
    inc = (rent * cap).quantize(CENT, ROUND_HALF_UP)
    return {"max_increase": inc, "max_new_rent": rent + inc}


def tfsa_penalty(excess: Decimal, months: int) -> Decimal:
    return (excess * TFSA_MONTHLY_RATE * months).quantize(CENT, ROUND_HALF_UP)


def expected(query: str, key: dict) -> ExpectedAnswer | None:
    rent = first_num(r"\$\s?([\d,]+(?:\.\d+)?)\s*/\s*month", query)
    excess = first_num(r"over-?contributed\s+\$\s?([\d,]+(?:\.\d+)?)", query)
    months = first_num(r"for\s+(\d+)\s+months?", query)
    req: list[RequiredValue] = []
    details: dict = {}
    if rent is not None:
        c = rent_cap(rent)
        req += [RequiredValue("Maximum lawful rent increase", money(c["max_increase"]), "CAD"),
                RequiredValue("Maximum new rent", money(c["max_new_rent"]), "CAD")]
        details |= {k: str(v) for k, v in c.items()}
        pct = first_num(r"increases?\s+by\s+(\d+(?:\.\d+)?)\s*%", query)
        if pct is not None:
            details["proposed_pct"] = str(pct)
            details["proposed_lawful"] = bool(pct <= BC_CAP_2026 * 100)
    if excess is not None and months is not None:
        p = tfsa_penalty(excess, int(months))
        req.append(RequiredValue("CRA TFSA penalty", money(p), "CAD"))
        details["tfsa_penalty"] = str(p)
    if not req:
        return None
    forb = tuple(ForbiddenPattern(f["label"], f["pattern"]) for f in key.get("forbidden", []))
    return ExpectedAnswer("tenancy_tax", tuple(req), forb, details)
