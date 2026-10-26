import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas import FaqCard, InvoiceAuditCard, RaceRequest, TriageCard


def _finding(billed=43200, expected=36000, disc=7200):
    return {
        "line_item": "SLA credit", "billed_usd": billed, "expected_usd": expected,
        "discrepancy_usd": disc, "policy_clause": "SLA Section 3",
    }


def _card(**over):
    base = {
        "vendor": "Northwind", "invoice_id": "INV-2291", "verdict": "overbilled",
        "findings": [_finding(), _finding(2400, 0, 2400)], "total_discrepancy_usd": 9600,
        "billed_total_usd": 45600, "approved_payout_usd": 36000, "citations": ["a#1"],
    }
    return {**base, **over}


def test_valid_invoice_card_and_json_money_is_a_number():
    card = InvoiceAuditCard.model_validate(_card())
    assert card.total_discrepancy_usd == Decimal(9600)
    dumped = json.loads(card.model_dump_json())
    assert dumped["total_discrepancy_usd"] == 9600 and isinstance(dumped["findings"][0]["billed_usd"], float)


def test_total_must_equal_sum_of_findings():
    with pytest.raises(ValidationError, match="sum of findings"):
        InvoiceAuditCard.model_validate(_card(total_discrepancy_usd=7200))


def test_approved_payout_must_equal_billed_total_minus_discrepancy():
    with pytest.raises(ValidationError, match="approved_payout_usd"):
        InvoiceAuditCard.model_validate(_card(approved_payout_usd=38400))


def test_credit_as_its_own_line_still_states_the_payout():
    """Live models often record the credit line as -4,800 billed vs -12,000 expected, so 36,000 appears in no
    line item. The card's approved_payout_usd field is where the answer key finds it (live run, 2026-10-26)."""
    from app.domains import check_answer, expected_answer
    from tests.heroes import B2B_HERO

    card = InvoiceAuditCard.model_validate(_card(findings=[_finding(-4800, -12000, 7200), _finding(2400, 0, 2400)]))
    v = check_answer(card, expected_answer("b2b_sla", "hallucination_trap", B2B_HERO))
    assert v.correct, v.required


def test_line_discrepancy_must_equal_billed_minus_expected():
    with pytest.raises(ValidationError, match="discrepancy"):
        InvoiceAuditCard.model_validate(_card(findings=[_finding(disc=1)], total_discrepancy_usd=1))


def test_verdict_must_match_sign_of_discrepancy():
    with pytest.raises(ValidationError, match="verdict"):
        InvoiceAuditCard.model_validate(_card(verdict="compliant"))


def test_citations_required():
    with pytest.raises(ValidationError):
        InvoiceAuditCard.model_validate(_card(citations=[]))


def test_triage_enums_and_length_limits():
    TriageCard(category="access", priority="P3", summary="x", suggested_queue="IT-ACCESS")
    with pytest.raises(ValidationError):
        TriageCard(category="access", priority="P0", summary="x", suggested_queue="q")
    with pytest.raises(ValidationError):
        TriageCard(category="access", priority="P3", summary="x" * 201, suggested_queue="q")


def test_faq_confidence_bounds():
    with pytest.raises(ValidationError):
        FaqCard(answer="a", confidence=1.5)


def test_race_request_validation():
    with pytest.raises(ValidationError):
        RaceRequest(query="")
    with pytest.raises(ValidationError):
        RaceRequest(query="x" * 2001)
    with pytest.raises(ValidationError):
        RaceRequest(query="ok", session_id="bad id!")
    # preset_id is validated against the requested domain's presets in the API (422), not in the schema.
    with pytest.raises(ValidationError):
        RaceRequest(query="ok", preset_id="Not A Valid Id!")
    with pytest.raises(ValidationError):
        RaceRequest(query="ok", domain="finance")
    with pytest.raises(ValidationError):
        RaceRequest(query="ok", model_mode="llama-3.3-70b-versatile")
