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
        "findings": [_finding(), _finding(2400, 0, 2400)], "total_discrepancy_usd": 9600, "citations": ["a#1"],
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
