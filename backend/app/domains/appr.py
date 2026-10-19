"""Canadian APPR delay compensation + baggage fee refund calculator."""
import re
from decimal import Decimal

from ._parse import first_num, money
from .types import ExpectedAnswer, ForbiddenPattern, RequiredValue

# (min hours inclusive, max hours exclusive, large carrier CAD, small carrier CAD)
TIERS = [(3, 6, 400, 125), (6, 9, 700, 250), (9, None, 1000, 500)]
BAGGAGE_LATE_HOURS = 24  # a bag is refundable when delivered more than this long after the passenger


def delay_compensation(delay_hours: Decimal, large_carrier: bool = True) -> Decimal:
    for lo, hi, large, small in TIERS:
        if delay_hours >= lo and (hi is None or delay_hours < hi):
            return Decimal(large if large_carrier else small)
    return Decimal(0)


def baggage_refund(bags: int, fee: Decimal, hours_late: Decimal | None) -> Decimal:
    """Per-bag fee refund; a bag with unknown lateness is treated as late (the prompt asked about refunds)."""
    if hours_late is not None and hours_late <= BAGGAGE_LATE_HOURS:
        return Decimal(0)
    return fee * bags


def compute(delay_hours: Decimal, passengers: int, bags: int, fee: Decimal, bag_hours_late: Decimal | None,
            large_carrier: bool = True) -> dict:
    per_pax = delay_compensation(delay_hours, large_carrier)
    payout = per_pax * passengers
    refund = baggage_refund(bags, fee, bag_hours_late)
    return {"per_passenger": per_pax, "payout": payout, "baggage_refund": refund, "total": payout + refund,
            "delay_hours": delay_hours, "passengers": passengers, "large_carrier": large_carrier}


def expected(query: str, key: dict) -> ExpectedAnswer | None:
    hours = first_num(r"delayed\s+(?:by\s+)?(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b", query) or first_num(
        r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s+(?:late|delayed)\b", query
    )
    if hours is None:
        return None
    pax_d = first_num(r"(\d+)\s+passengers?\b", query)
    bags_d = first_num(r"(\d+)\s+checked\s+bags?\b", query)
    fee = first_num(r"\$\s?(\d+(?:\.\d+)?)\s+fee", query)
    late = first_num(r"arrived\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s+late", query)
    large = not re.search(r"small carrier|regional carrier", query, re.I)
    bags = int(bags_d) if bags_d is not None else 0
    r = compute(hours, int(pax_d) if pax_d is not None else 1, bags, fee or Decimal(0), late, large)
    if r["payout"] == 0:
        return None  # delay outside every compensation band: a key of "0" would prove nothing
    req = [RequiredValue("APPR cash payout", money(r["payout"]), "CAD")]
    if bags and fee:
        req += [RequiredValue("Baggage fee refund", money(r["baggage_refund"]), "CAD"),
                RequiredValue("Combined total", money(r["total"]), "CAD")]
    forb = tuple(ForbiddenPattern(f["label"], f["pattern"]) for f in key.get("forbidden", []))
    return ExpectedAnswer("appr", tuple(req), forb, {k: str(v) for k, v in r.items()})
