"""Deterministic order-audit calculator over the footlong ingredient matrix (the corpus file is the single source)."""
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .types import ExpectedAnswer, ForbiddenPattern, RequiredValue

MATRIX_DOC = "footlong_ingredient_matrix.md"
DEFAULT_CAPS = {"kcal": 950, "protein": 55, "sodium": 1800}
_ROW = re.compile(r"^\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<kcal>\d+)\s*\|\s*(?P<protein>\d+)\s*\|\s*(?P<sodium>\d+)\s*\|\s*(?P<allergens>[^|]*?)\s*\|\s*$")
_MULT = {"double": 2, "triple": 3, "extra": 2}


@dataclass(frozen=True)
class Ingredient:
    name: str
    kcal: int
    protein: int
    sodium: int
    allergens: tuple[str, ...]

    @property
    def dairy(self) -> bool:
        return "milk" in self.allergens


def _default_matrix_path() -> Path:
    from app.config import BACKEND_DIR

    return BACKEND_DIR / "data" / "corpus" / "nutrition" / MATRIX_DOC


@lru_cache(maxsize=4)
def load_matrix(path: str | None = None) -> dict[str, Ingredient]:
    p = Path(path) if path else _default_matrix_path()
    out: dict[str, Ingredient] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line.strip())
        if not m:
            continue
        al = tuple(a.strip().lower() for a in m["allergens"].split(",") if a.strip() and a.strip().lower() != "none")
        out[m["name"].lower()] = Ingredient(m["name"], int(m["kcal"]), int(m["protein"]), int(m["sodium"]), al)
    return out


def _aliases(name: str) -> list[str]:
    n = name.lower()
    al = [n]
    for suffix in (" bread", " cheese", " sauce"):
        if n.endswith(suffix) and len(n) - len(suffix) >= 5:
            al.append(n[: -len(suffix)])
    return al


def parse_order(query: str, matrix: dict[str, Ingredient] | None = None) -> list[tuple[Ingredient, int]]:
    """Ingredients named in the prompt (longest alias first, no overlaps) with their portion multiplier."""
    matrix = matrix or load_matrix()
    q = query.lower()
    cands: list[tuple[str, Ingredient]] = []
    for ing in matrix.values():
        for a in _aliases(ing.name):
            cands.append((a, ing))
    cands.sort(key=lambda c: -len(c[0]))
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, Ingredient, int]] = []
    for alias, ing in cands:
        for m in re.finditer(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", q):
            s, e = m.span()
            if any(s < te and e > ts for ts, te in taken):
                continue
            if any(i is ing for _, i, _ in found):
                continue
            mult = 1
            pre = re.search(r"\b(double|triple|extra)\s+(?:[a-z&-]+\s+){0,3}$", q[max(0, s - 40):s])
            if pre:
                mult = _MULT[pre.group(1)]
            taken.append((s, e))
            found.append((s, ing, mult))
            break
    found.sort(key=lambda t: t[0])
    return [(i, m) for _, i, m in found]


def totals(order: list[tuple[Ingredient, int]]) -> dict:
    return {
        "kcal": sum(i.kcal * m for i, m in order),
        "protein": sum(i.protein * m for i, m in order),
        "sodium": sum(i.sodium * m for i, m in order),
        "dairy_items": [i.name for i, _ in order if i.dairy],
        "allergens": sorted({a for i, _ in order for a in i.allergens}),
    }


def audit(order: list[tuple[Ingredient, int]], caps: dict[str, int] | None = None, zero_dairy: bool = True) -> dict:
    caps = {**DEFAULT_CAPS, **(caps or {})}
    t = totals(order)
    violations = []
    if t["kcal"] >= caps["kcal"]:
        violations.append(f"calories {t['kcal']} kcal is not below {caps['kcal']}")
    if t["protein"] <= caps["protein"]:
        violations.append(f"protein {t['protein']} g is not above {caps['protein']}")
    if t["sodium"] >= caps["sodium"]:
        violations.append(f"sodium {t['sodium']} mg is not below {caps['sodium']}")
    if zero_dairy and t["dairy_items"]:
        violations.append("dairy present in: " + ", ".join(t["dairy_items"]))
    return {**t, "caps": caps, "violations": violations}


def _cap(pattern: str, query: str) -> int | None:
    m = re.search(pattern, query, re.I)
    return int(m.group(1).replace(",", "")) if m else None


def expected(query: str, key: dict) -> ExpectedAnswer | None:
    order = parse_order(query)
    if len(order) < 3:
        return None
    caps = {
        "kcal": _cap(r"<\s*([\d,]+)\s*kcal", query),
        "protein": _cap(r">\s*([\d,]+)\s*g\s*protein", query),
        "sodium": _cap(r"<\s*([\d,]+)\s*mg\s*sodium", query),
    }
    caps = {k: v for k, v in caps.items() if v is not None}
    zero_dairy = bool(re.search(r"zero dairy|no dairy|dairy[- ]free", query, re.I))
    a = audit(order, caps, zero_dairy)
    req = (
        RequiredValue("Total calories", str(a["kcal"]), "kcal"),
        RequiredValue("Total protein", str(a["protein"]), "g"),
        RequiredValue("Total sodium", str(a["sodium"]), "mg"),
    )
    forb = tuple(ForbiddenPattern(f["label"], f["pattern"]) for f in key.get("forbidden", []))
    details = {**a, "order": [(i.name, m) for i, m in order]}
    return ExpectedAnswer("nutrition", req, forb, details)
