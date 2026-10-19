"""Small helpers for pulling numbers out of free-text prompts."""
import re
from decimal import Decimal, InvalidOperation

CENT = Decimal("0.01")


def num(s: str) -> Decimal | None:
    try:
        return Decimal(s.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def first_num(pattern: str, text: str, flags: int = re.I) -> Decimal | None:
    m = re.search(pattern, text, flags)
    return num(m.group(1)) if m else None


def money(d: Decimal) -> str:
    return f"{d.quantize(CENT):.2f}"
