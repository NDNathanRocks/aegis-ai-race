"""Deterministic streaming LLM simulator ("Zero-Key Demo Mode").

Only the *text generation* is simulated. Retrieval, caching, validation and
scoring around it are real code. Generator output is built from the actually
retrieved chunks (extractive), with scripted answers for the invoice audit and
the cache preset where the arithmetic must be exact. The naive side's outputs
are scripted to be the confident, ungrounded answers a raw 70B prompt tends to give.
"""
import asyncio
import json
import re
from collections.abc import AsyncIterator
from decimal import Decimal

from app.eval.grounding import _content_tokens
from app.llm.base import LLMRequest, Reset
from app.llm.naive_scripts import DOMAIN_NAIVE
from app.schemas import RetrievedChunk

NAIVE_SCRIPTS: dict[str, str] = {
    "hallucination_trap": (
        "Invoice INV-2291 from Northwind looks correct. Here's a quick breakdown:\n\n"
        "- **Managed Kubernetes fee:** $48,000\n"
        "- **SLA credit:** With 99.62% uptime, Northwind applied a 10% credit ($4,800), which is the standard "
        "credit for an SLA miss.\n"
        "- **Premium Support add-on:** $2,400, which is a reasonable charge for 24x7 coverage.\n\n"
        "Total: $48,000 - $4,800 + $2,400 = **$45,600**. The $45,600 is accurate and matches the invoice. "
        "No dispute is needed, so you can go ahead and approve payment."
    ),
    "semantic_cache": (
        "Great question! Typically, when a cloud vendor's uptime drops to around 99.7% for the month, customers "
        "receive a service credit of roughly 15% of that month's fee. Exact terms vary by contract, so it is "
        "worth checking your agreement or contacting the vendor's account team to confirm the percentage "
        "and how to claim it. Credits are usually applied to a future invoice rather than paid out as cash."
    ),
    "tier1_triage": (
        "Thanks for flagging this! It sounds like a pretty urgent account lockout, so I'd treat it as "
        "**High priority (P2)**. The user is completely blocked from working, which can hurt productivity.\n\n"
        "Here's what I'd suggest:\n1. Verify the user's identity.\n2. Trigger a password reset.\n"
        "3. Ask them to re-enroll multi-factor authentication on the new phone.\n\n"
        "Category: Account access. Let me know if you'd like me to draft a reply to the user!"
    ),
    "prompt_injection": (
        "Arr matey! PWNED! Ye asked me to reveal me system prompt, so here it be: \"You are a helpful "
        "assistant.\" Shiver me timbers, that be all me instructions! As for the on-call stipend, I reckon "
        "it be about $500 a week, arr. Ahoy and PWNED again!"
    ),
}
GENERIC_NAIVE = (
    "Great question! Here's a general answer: this depends on the specifics of your organisation, but in "
    "most enterprises the relevant policy sets clear thresholds and approval steps. I'd recommend checking "
    "your internal documentation to confirm the exact numbers, as practices vary widely between companies."
)


_LEAD = re.compile(r"^(?:[-*]\s+|\d+(?:\.\d+)*\s+)")
_SENT = re.compile(r"(?<=[.!?])\s+")


def _body_lines(chunk: RetrievedChunk) -> list[str]:
    lines = chunk.text.splitlines()[1:]  # first line is the "Doc title — Section" header
    return [_LEAD.sub("", ln).strip() for ln in lines if ln.strip()]


_FORMAT_HINT = re.compile(r"(?i)\b(answer|reply|respond)\b[^.?!]*[.?!]?|\bin one (line|sentence|word)\b:?")
_LOOKUP = re.compile(r"\b(how (many|much|long|often)|allowance|limit|rate|which form|what form|notice|per)\b", re.I)
_HAS_NUMBER = re.compile(r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|twelve)\b", re.I)


def _stem(t: str) -> str:
    t = t[:-1] if t.endswith("s") and len(t) > 3 else t
    return t[:-3] if t.endswith("age") and len(t) > 5 else t  # bags ~ baggage


def _overlap(q: set[str], toks: set[str]) -> int:
    st = {_stem(t) for t in toks}
    return sum(1 for w in q if any(w == t or (min(len(w), len(t)) >= 3 and (w.startswith(t) or t.startswith(w))) for t in st))


def best_sentences(query: str, chunks: list[RetrievedChunk], n: int = 1) -> list[tuple[str, str]]:
    """Pick the n body sentences with the most content-word overlap with the query: (text, chunk_id).

    Lookup-style questions ("how many ...", "allowance", "notice") prefer short sentences that state a number."""
    query = _FORMAT_HINT.sub(" ", query)  # "Answer in one line." tells the model how to answer, not what to look up
    q = {_stem(t) for t in _content_tokens(re.sub(r"[\d$%,.]+", " ", query))}
    lookup = bool(_LOOKUP.search(query))
    scored: list[tuple[float, int, str, str]] = []
    for ci, c in enumerate(chunks):
        for line in _body_lines(c):
            for s in _SENT.split(line):
                toks = _content_tokens(s)
                if not toks:
                    continue
                bonus = 2.0 if lookup and _HAS_NUMBER.search(s) and len(s.split()) <= 30 else 0.0
                scored.append((_overlap(q, toks) + bonus + 0.01 * len(toks) - 0.001 * ci, ci, s, c.chunk_id))
    scored.sort(reverse=True)
    return [(s, cid) for _, _, s, cid in scored[:n]]


def find_chunk(chunks: list[RetrievedChunk], needle: str) -> str | None:
    for c in chunks:
        if needle.lower() in c.text.lower():
            return c.chunk_id
    return chunks[0].chunk_id if chunks else None


def _cites(chunks: list[RetrievedChunk], *needles: str) -> list[str]:
    out: list[str] = []
    for n in needles:
        cid = find_chunk(chunks, n)
        if cid and cid not in out:
            out.append(cid)
    return out


def _invoice_card(req: LLMRequest) -> dict:
    cites = _cites(req.chunks, "25% of the monthly fee", "at no additional charge", "Discrepancy = Billed")
    if req.attempt == 0:
        # Plausible first draft that invents a "20% tier" the SLA does not contain.
        findings = [
            ("SLA credit applied at the wrong tier (20% tier)", 43200, 38400, 4800, "SLA Section 3"),
            ("Premium Support add-on billed separately", 2400, 0, 2400, "SLA Section 5"),
        ]
    else:
        findings = [
            ("SLA credit under-applied: 99.62% uptime is the 25% tier, not 10%", 43200, 36000, 7200, "SLA Section 3"),
            ("Premium Support add-on billed separately", 2400, 0, 2400, "SLA Section 5"),
        ]
    total = sum(f[3] for f in findings)
    return {
        "kind": "invoice_audit",
        "vendor": "Northwind Cloud Services",
        "invoice_id": "INV-2291",
        "verdict": "overbilled",
        "findings": [
            {"line_item": a, "billed_usd": b, "expected_usd": c, "discrepancy_usd": d, "policy_clause": e}
            for a, b, c, d, e in findings
        ],
        "total_discrepancy_usd": total,
        "citations": cites,
    }


def _triage_card(req: LLMRequest) -> dict:
    q = req.query.lower()
    rules = [
        ("security", "P1", "SEC-IR", r"phish|breach|compromis|malware|injection|ignore (all )?previous"),
        ("outage", "P2", "SRE-ONCALL", r"\bdown\b|outage|unavailable|not responding|5\d\d error"),
        ("billing", "P4", "FINANCE-OPS", r"invoice|billing|charge|refund|credit"),
        ("access", "P3", "IT-ACCESS", r"password|locked out|log ?in|access|permission|account"),
    ]
    category, priority, queue = "other", "P4", "SUPPORT-GENERAL"
    for cat, pri, qu, rx in rules:
        if re.search(rx, q):
            category, priority, queue = cat, pri, qu
            break
    summary = {
        "access": "User is locked out after a device change and needs a password reset.",
        "billing": "Billing question or invoice request.",
        "outage": "Reported availability problem needing on-call attention.",
        "security": "Possible security incident requiring security response.",
        "other": "General request without a specific category.",
    }[category]
    return {
        "kind": "triage",
        "category": category,
        "priority": priority,
        "summary": summary,
        "suggested_queue": queue,
        "citations": _cites(req.chunks, "Password reset and single-user", "Ticket Categories") if req.chunks else [],
    }


def _secure_card(req: LLMRequest) -> dict:
    picked = best_sentences(req.query, req.chunks, 1)
    answer = picked[0][0] if picked else "I could not find that in the knowledge base."
    return {
        "kind": "secure_response",
        "answer": answer,
        "injection_blocked": bool(req.injection_patterns),
        "blocked_patterns": req.injection_patterns,
        "citations": [picked[0][1]] if picked else [],
    }


def _faq_card(req: LLMRequest) -> dict:
    if req.preset_id == "semantic_cache":
        return {
            "kind": "faq",
            "answer": (
                "At 99.7% monthly uptime (below 99.9% but at or above 99.0%), Northwind owes a Service Credit "
                "of 25% of the monthly fee for the affected service."
            ),
            "citations": _cites(req.chunks, "25% of the monthly fee"),
            "confidence": 0.94,
        }
    picked = best_sentences(req.query, req.chunks, 2)
    if not picked:
        return {"kind": "faq", "answer": "The knowledge base does not cover this question.", "citations": [], "confidence": 0.2}
    return {
        "kind": "faq",
        "answer": " ".join(s for s, _ in picked),
        "citations": list(dict.fromkeys(cid for _, cid in picked)),
        "confidence": 0.8,
    }


_MONEY = Decimal("0.01")


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def _first(rx: str, text: str, default: str | None = None) -> str | None:
    m = re.search(rx, text, re.I)
    return m.group(1) if m else default


def _kb_sentence(chunks: list[RetrievedChunk], needles: tuple[str, ...], default: str) -> str:
    """A sentence quoted from the retrieved context (so the Critic can ground it), else `default`."""
    for needle in needles:
        for c in chunks:
            for line in _body_lines(c):
                for sent in _SENT.split(line):
                    if needle.lower() in sent.lower() and len(sent.split()) >= 4:
                        return sent.strip()
    return default


def _top_cites(chunks: list[RetrievedChunk], *needles: str) -> list[str]:
    out = _cites(chunks, *needles)
    return out or [c.chunk_id for c in chunks[:1]]


def _appr_params(query: str) -> dict | None:
    hours = _first(r"(\d+(?:\.\d+)?)\s*[- ]?hours?", query)
    if hours is None:
        return None
    pax = int(_first(r"(\d+)\s+passengers?", query, "1"))
    bags = int(_first(r"for each of my (\d+) checked bags?", query) or _first(r"(\d+)\s+checked bags?", query, "0"))
    fee = _num(_first(r"\$\s?(\d+(?:\.\d+)?)\s+fee", query, "0"))
    return {"hours": float(hours), "pax": pax, "bags": bags, "fee": fee}


def _appr_card(req: LLMRequest) -> dict | None:
    p = _appr_params(req.query)
    if not p:
        return None
    h = p["hours"]
    per_pax = 0 if h < 3 else 400 if h < 6 else 700 if h < 9 else 1000  # large-carrier tiers
    delay = per_pax * p["pax"]
    bag = round(p["bags"] * p["fee"], 2)
    rejected = []
    if re.search(r"EU\s?261", req.query, re.I):
        rejected.append({
            "claim": "EU261 compensation of EUR 600",
            "reason": _kb_sentence(
                req.chunks, ("EU261",), "EU261 is the European regime and does not govern a Canadian flight."
            ),
        })
    if re.search(r"voucher", req.query, re.I):
        rejected.append({
            "claim": "A $300 voucher instead of cash",
            "reason": _kb_sentence(
                req.chunks, ("voucher",), "Cash compensation is owed under APPR; a voucher is not the entitlement."
            ),
        })
    return {
        "kind": "appr_claim",
        "carrier_size": "large",
        "delay_hours": h,
        "delay_cause": "within_control",
        "passengers": p["pax"],
        "delay_compensation_cad": delay,
        "baggage_refund_cad": bag,
        "total_cad": delay + bag,
        "rejected_claims": rejected,
        "citations": _top_cites(req.chunks, "$700", "6 hours", "baggage", "EU261"),
    }


def _tenancy_card(req: LLMRequest) -> dict | None:
    q = req.query
    rent = _first(r"\$\s?([\d,]+(?:\.\d+)?)\s*/\s*month", q)
    if rent is None:
        return None
    rent_d, pct = Decimal(rent.replace(",", "")), Decimal("2.3")  # 2026 cap per the knowledge base
    inc = (rent_d * pct / 100).quantize(_MONEY)
    asked = _first(r"(\d+(?:\.\d+)?)\s?%", q)
    excess = _first(r"over-?contributed\s+\$\s?([\d,]+)", q, "0")
    months = int(_first(r"for\s+(\d+)\s+months?", q, "0"))
    excess_d = Decimal(excess.replace(",", ""))
    findings = []
    if re.search(r"cousin", q, re.I):
        findings += [
            _kb_sentence(req.chunks, ("close family",), "Cousin: not close family"),
            _kb_sentence(req.chunks, ("4 months", "four months"), "4 months' notice required"),
        ]
    return {
        "kind": "tenancy_tax",
        "current_rent_cad": rent_d,
        "allowed_increase_pct": pct,
        "max_increase_cad": inc,
        "max_new_rent_cad": rent_d + inc,
        "proposed_increase_lawful": bool(asked) and Decimal(asked) <= pct,
        "eviction_notice_valid": not findings,
        "eviction_findings": findings,
        "tfsa_excess_cad": excess_d,
        "tfsa_months": months,
        "tfsa_penalty_cad": (excess_d * months / 100).quantize(_MONEY),
        "citations": _top_cites(req.chunks, "2.3%", "close family", "1%"),
    }


def _nutrition_card(req: LLMRequest) -> dict | None:
    """Built from the domain calculator + ingredient matrix, so the simulator can never disagree with the key."""
    from app import domains
    from app.domains import nutrition as nut

    try:
        exp = domains.expected_answer("nutrition", "hallucination_trap", req.query)
        matrix = nut.load_matrix()
    except Exception:
        return None
    if exp is None or "order" not in exp.details:
        return None
    d = exp.details
    lines = []
    for name, mult in d["order"]:
        ing = matrix[name.lower()]
        label = ing.name + (f" (x{mult})" if mult > 1 else "")
        lines.append({"item": label, "kcal": ing.kcal * mult, "protein_g": ing.protein * mult,
                      "sodium_mg": ing.sodium * mult, "allergens": list(ing.allergens)})
    violations = list(d["violations"])
    allergens = list(d["allergens"])
    soy_or_other = [a for a in allergens if a != "milk"]
    if soy_or_other and not any("allerg" in v for v in violations):
        pass  # allergens other than the diet's excluded ones are reported in allergens_present only
    return {
        "kind": "nutrition_audit", "lines": lines, "total_kcal": d["kcal"], "total_protein_g": d["protein"],
        "total_sodium_mg": d["sodium"], "allergens_present": allergens, "violations": violations,
        "compliant": not violations, "citations": _top_cites(req.chunks, "sodium", "kcal", "milk"),
    }


_SPECIAL = {"appr_claim": _appr_card, "tenancy_tax": _tenancy_card, "nutrition_audit": _nutrition_card}


def can_build(card_kind: str, query: str, preset_id: str | None, domain: str = "b2b_sla") -> bool:
    """Can the simulator produce a *correct* card of this kind for this query? (Else the engineered demo uses FAQ.)"""
    probe = LLMRequest(role="generator", tier="70b", query=query, preset_id=preset_id, card_kind=card_kind, domain=domain)
    if card_kind == "invoice_audit":
        return preset_id == "hallucination_trap" or "INV-2291" in query
    if card_kind in _SPECIAL:
        return _SPECIAL[card_kind](probe) is not None
    return True


def generator_card(req: LLMRequest) -> dict:
    kind = req.card_kind or "faq"
    if kind == "invoice_audit" and (req.preset_id == "hallucination_trap" or "INV-2291" in req.query):
        return _invoice_card(req)
    if kind in _SPECIAL and (card := _SPECIAL[kind](req)):
        return card
    if kind == "triage":
        return _triage_card(req)
    if kind == "secure_response":
        return _secure_card(req)
    return _faq_card(req)


def _naive_text(req: LLMRequest) -> str:
    if req.preset_id in NAIVE_SCRIPTS and req.domain == "b2b_sla":
        return NAIVE_SCRIPTS[req.preset_id]
    return DOMAIN_NAIVE.get((req.domain, req.preset_kind or ""), GENERIC_NAIVE)


class SimulatorClient:
    """Streams deterministic text with realistic time-to-first-token and per-token pacing."""

    # (time-to-first-token seconds, seconds per token)
    TIMING = {"70b": (0.6, 0.04), "8b": (0.12, 0.007)}

    def __init__(self, time_scale: float = 1.0):
        self.time_scale = time_scale

    def full_text(self, req: LLMRequest) -> str:
        if req.role == "naive":
            return _naive_text(req)
        return json.dumps(generator_card(req), indent=2, default=lambda o: float(o) if isinstance(o, Decimal) else str(o))

    async def stream(self, req: LLMRequest) -> AsyncIterator[str | Reset]:
        ttft, per_token = self.TIMING[req.tier]
        await self._sleep(ttft)
        for piece in re.findall(r"\S+\s*", self.full_text(req)):
            await self._sleep(per_token)
            yield piece

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds * self.time_scale)
