"""All Pydantic models: requests, pipeline telemetry and structured outputs."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer, model_validator

Side = Literal["naive", "engineered"]
Tier = Literal["8b", "70b"]
Mode = Literal["live", "demo"]
Domain = Literal["travel_appr", "bc_tenancy_cra", "nutrition", "b2b_sla"]
ContextMode = Literal["full_kb", "none"]  # what the NAIVE side is given; engineered always uses RRF chunks
ModelMode = Literal["70b", "8b", "auto"]  # server-side allowlist; clients never send a model id
Provider = Literal["groq", "simulator"]
UsageSource = Literal["provider", "estimate"]
CardKind = Literal[
    "invoice_audit", "triage", "secure_response", "faq", "appr_claim", "tenancy_tax", "nutrition_audit"
]
# Decimal in Python (exact money math), JSON number on the wire (pydantic's default is a string).
Money = Annotated[Decimal, PlainSerializer(lambda d: float(d), return_type=float, when_used="json")]


class RaceRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    # Backend default keeps pre-v2 callers/tests on the Northwind corpus; the v2 UI always sends `domain`.
    domain: Domain = "b2b_sla"
    context_mode: ContextMode = "full_kb"
    model_mode: ModelMode = "70b"
    # Shared by the naive and engineered requests of one race; the server creates one RaceRun per id.
    race_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")
    preset_id: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_]+$")
    variant: Literal["primary", "paraphrase"] = "primary"
    force_demo: bool = False
    session_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tier: Tier = "70b"
    cost_usd: float = 0.0
    source: UsageSource = "estimate"  # "provider" = counted by Groq (`usage`), "estimate" = ~4 chars/token (demo)

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


class RejectedClaim(BaseModel):
    claim: str
    reason: str


class AppRClaimCard(BaseModel):
    """Canadian APPR flight-delay + baggage claim."""

    kind: Literal["appr_claim"] = "appr_claim"
    carrier_size: Literal["large", "small"]
    delay_hours: float = Field(ge=0)
    delay_cause: Literal["within_control", "within_control_safety", "outside_control"]
    passengers: int = Field(ge=1)
    delay_compensation_cad: Money
    baggage_refund_cad: Money
    total_cad: Money
    rejected_claims: list[RejectedClaim] = []
    citations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _total(self):
        if self.delay_compensation_cad + self.baggage_refund_cad != self.total_cad:
            raise ValueError(
                f"total_cad {self.total_cad} != delay {self.delay_compensation_cad} + baggage {self.baggage_refund_cad}"
            )
        return self


class TenancyTaxCard(BaseModel):
    """BC rent-increase / landlord-use eviction audit plus CRA TFSA over-contribution penalty."""

    kind: Literal["tenancy_tax"] = "tenancy_tax"
    current_rent_cad: Money
    allowed_increase_pct: Money  # e.g. 2.3
    max_increase_cad: Money
    max_new_rent_cad: Money
    proposed_increase_lawful: bool
    eviction_notice_valid: bool
    eviction_findings: list[str] = []
    tfsa_excess_cad: Money
    tfsa_months: int = Field(ge=0)
    tfsa_penalty_cad: Money
    citations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _math(self):
        cent = Decimal("0.01")
        inc = (self.current_rent_cad * self.allowed_increase_pct / 100).quantize(cent)
        if inc != self.max_increase_cad:
            raise ValueError(f"max_increase_cad {self.max_increase_cad} != rent x pct = {inc}")
        if self.current_rent_cad + self.max_increase_cad != self.max_new_rent_cad:
            raise ValueError("max_new_rent_cad != current_rent_cad + max_increase_cad")
        pen = (self.tfsa_excess_cad * self.tfsa_months / 100).quantize(cent)
        if pen != self.tfsa_penalty_cad:
            raise ValueError(f"tfsa_penalty_cad {self.tfsa_penalty_cad} != excess x 1% x months = {pen}")
        return self


class NutritionLine(BaseModel):
    item: str
    kcal: int = Field(ge=0)
    protein_g: Money
    sodium_mg: int = Field(ge=0)
    allergens: list[str] = []


class NutritionAuditCard(BaseModel):
    kind: Literal["nutrition_audit"] = "nutrition_audit"
    lines: list[NutritionLine] = Field(min_length=1)
    total_kcal: int
    total_protein_g: Money
    total_sodium_mg: int
    allergens_present: list[str]
    violations: list[str]
    compliant: bool
    citations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _totals(self):
        if sum(ln.kcal for ln in self.lines) != self.total_kcal:
            raise ValueError("total_kcal != sum of lines")
        if sum((ln.protein_g for ln in self.lines), Decimal(0)) != self.total_protein_g:
            raise ValueError("total_protein_g != sum of lines")
        if sum(ln.sodium_mg for ln in self.lines) != self.total_sodium_mg:
            raise ValueError("total_sodium_mg != sum of lines")
        if self.compliant != (not self.violations):
            raise ValueError("compliant must be true exactly when violations is empty")
        return self


StructuredCard = Annotated[
    InvoiceAuditCard | TriageCard | SecureResponseCard | FaqCard | AppRClaimCard | TenancyTaxCard | NutritionAuditCard,
    Field(discriminator="kind"),
]
CARD_MODELS: dict[str, type[BaseModel]] = {
    "invoice_audit": InvoiceAuditCard,
    "triage": TriageCard,
    "secure_response": SecureResponseCard,
    "faq": FaqCard,
    "appr_claim": AppRClaimCard,
    "tenancy_tax": TenancyTaxCard,
    "nutrition_audit": NutritionAuditCard,
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
