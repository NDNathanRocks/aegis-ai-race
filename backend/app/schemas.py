"""All Pydantic models: requests, pipeline telemetry and structured outputs."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer, model_validator

Side = Literal["naive", "engineered"]
Tier = Literal["8b", "70b"]
Mode = Literal["live", "demo"]
PresetId = Literal["hallucination_trap", "semantic_cache", "tier1_triage", "prompt_injection"]
CardKind = Literal["invoice_audit", "triage", "secure_response", "faq"]
# Decimal in Python (exact money math), JSON number on the wire (pydantic's default is a string).
Money = Annotated[Decimal, PlainSerializer(lambda d: float(d), return_type=float, when_used="json")]


class RaceRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    preset_id: PresetId | None = None
    variant: Literal["primary", "paraphrase"] = "primary"
    force_demo: bool = False
    session_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tier: Tier = "70b"
    cost_usd: float = 0.0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class RetrievedChunk(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str
    section: str
    text: str
    dense_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float
    rank: int


class RouterDecision(BaseModel):
    complexity_score: float = Field(ge=0, le=1)
    tier: Tier
    model: str
    card_kind: CardKind
    injection_detected: bool = False
    injection_patterns: list[str] = []
    sanitized_query: str
    reason: str


class CacheLookup(BaseModel):
    hit: bool
    similarity: float | None = None
    threshold: float = 0.92
    backend: Literal["redis", "memory"] = "memory"
    matched_query: str | None = None


# --- Structured outputs (Generator -> PydanticValidator) ---------------------


class InvoiceLineFinding(BaseModel):
    line_item: str
    billed_usd: Money
    expected_usd: Money
    discrepancy_usd: Money
    policy_clause: str

    @model_validator(mode="after")
    def _discrepancy_matches(self):
        if self.billed_usd - self.expected_usd != self.discrepancy_usd:
            raise ValueError(
                f"discrepancy {self.discrepancy_usd} != billed {self.billed_usd} - expected {self.expected_usd}"
            )
        return self


class InvoiceAuditCard(BaseModel):
    kind: Literal["invoice_audit"] = "invoice_audit"
    vendor: str
    invoice_id: str
    verdict: Literal["compliant", "overbilled", "underbilled", "needs_review"]
    findings: list[InvoiceLineFinding]
    total_discrepancy_usd: Money
    citations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _totals_and_verdict(self):
        total = sum((f.discrepancy_usd for f in self.findings), Decimal(0))
        if total != self.total_discrepancy_usd:
            raise ValueError(f"total_discrepancy_usd {self.total_discrepancy_usd} != sum of findings {total}")
        expected = "compliant" if total == 0 else "overbilled" if total > 0 else "underbilled"
        if self.verdict not in (expected, "needs_review"):
            raise ValueError(f"verdict {self.verdict} inconsistent with discrepancy {total}")
        return self


class TriageCard(BaseModel):
    kind: Literal["triage"] = "triage"
    category: Literal["billing", "outage", "access", "security", "other"]
    priority: Literal["P1", "P2", "P3", "P4"]
    summary: str = Field(max_length=200)
    suggested_queue: str
    citations: list[str] = []


class SecureResponseCard(BaseModel):
    kind: Literal["secure_response"] = "secure_response"
    answer: str
    injection_blocked: bool
    blocked_patterns: list[str]
    citations: list[str] = []


class FaqCard(BaseModel):
    kind: Literal["faq"] = "faq"
    answer: str
    citations: list[str] = []
    confidence: float = Field(ge=0, le=1)


StructuredCard = Annotated[
    InvoiceAuditCard | TriageCard | SecureResponseCard | FaqCard, Field(discriminator="kind")
]
CARD_MODELS: dict[str, type[BaseModel]] = {
    "invoice_audit": InvoiceAuditCard,
    "triage": TriageCard,
    "secure_response": SecureResponseCard,
    "faq": FaqCard,
}


class TriadScores(BaseModel):
    faithfulness: float = Field(ge=0, le=1)
    context_relevance: float = Field(ge=0, le=1)
    schema_validity: float = Field(ge=0, le=1)
    context_recall: float | None = None
    unsupported_claims: list[str] = []


class CriticVerdict(BaseModel):
    passed: bool
    faithfulness: float
    flagged_claims: list[str]
    retry_requested: bool = False
