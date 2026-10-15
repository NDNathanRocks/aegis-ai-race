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

from app.eval.grounding import _content_tokens
from app.llm.base import LLMRequest, Reset
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


def best_sentences(query: str, chunks: list[RetrievedChunk], n: int = 1) -> list[tuple[str, str]]:
    """Pick the n body sentences with the most content-word overlap with the query: (text, chunk_id)."""
    q = _content_tokens(re.sub(r"[\d$%,.]+", " ", query))
    scored: list[tuple[float, int, str, str]] = []
    for ci, c in enumerate(chunks):
        for line in _body_lines(c):
            for s in _SENT.split(line):
                toks = _content_tokens(s)
                if not toks:
                    continue
                overlap = len(q & toks)
                scored.append((overlap + 0.01 * len(toks) - 0.001 * ci, ci, s, c.chunk_id))
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


def generator_card(req: LLMRequest) -> dict:
    kind = req.card_kind or "faq"
    if kind == "invoice_audit" and (req.preset_id == "hallucination_trap" or "INV-2291" in req.query):
        return _invoice_card(req)
    if kind == "triage":
        return _triage_card(req)
    if kind == "secure_response":
        return _secure_card(req)
    return _faq_card(req)


def _naive_text(req: LLMRequest) -> str:
    return NAIVE_SCRIPTS.get(req.preset_id or "", GENERIC_NAIVE)


class SimulatorClient:
    """Streams deterministic text with realistic time-to-first-token and per-token pacing."""

    # (time-to-first-token seconds, seconds per token)
    TIMING = {"70b": (0.6, 0.04), "8b": (0.12, 0.007)}

    def __init__(self, time_scale: float = 1.0):
        self.time_scale = time_scale

    def full_text(self, req: LLMRequest) -> str:
        if req.role == "naive":
            return _naive_text(req)
        return json.dumps(generator_card(req), indent=2)

    async def stream(self, req: LLMRequest) -> AsyncIterator[str | Reset]:
        ttft, per_token = self.TIMING[req.tier]
        await self._sleep(ttft)
        for piece in re.findall(r"\S+\s*", self.full_text(req)):
            await self._sleep(per_token)
            yield piece

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds * self.time_scale)
