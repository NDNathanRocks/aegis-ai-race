from decimal import Decimal

import pytest

from app import domains as dom
from app.domains import appr, invoice, nutrition, tenancy_tax
from app.domains.answer import number_pattern, value_found


def _hero(domain):
    return dom.get_domain(domain).presets[0]


def _key(domain, query=None):
    return dom.expected_answer(domain, "hallucination_trap", query or _hero(domain).query)


# --- calculators ---------------------------------------------------------------------------------------------------
def test_appr_hero_values():
    r = appr.compute(Decimal("6.5"), 1, 2, Decimal(35), Decimal(30))
    assert (r["payout"], r["baggage_refund"], r["total"]) == (700, 70, 770)


@pytest.mark.parametrize("hours,large,amount", [(2.9, True, 0), (3, True, 400), (5.99, True, 400), (6, True, 700),
                                                (9, True, 1000), (3, False, 125), (7, False, 250), (12, False, 500)])
def test_appr_bands(hours, large, amount):
    assert appr.delay_compensation(Decimal(str(hours)), large) == amount


def test_appr_bag_not_late_enough_is_not_refunded():
    assert appr.baggage_refund(2, Decimal(35), Decimal(20)) == 0


def test_tenancy_hero_values():
    c = tenancy_tax.rent_cap(Decimal(2400))
    assert str(c["max_increase"]) == "55.20" and str(c["max_new_rent"]) == "2455.20"
    assert str(tenancy_tax.tfsa_penalty(Decimal(4500), 3)) == "135.00"


def test_invoice_hero_values():
    a = invoice.audit(Decimal(48000), Decimal("99.62"), Decimal(45600))
    assert (a["credit_pct"], a["credit"], a["expected_total"], a["overbilled"]) == (25, 12000, 36000, 9600)
    assert invoice.credit_percent(Decimal("99.95")) == 0 and invoice.credit_percent(Decimal("99.9")) == 10
    assert invoice.credit_percent(Decimal("98.5")) == 50


def test_nutrition_hero_totals_and_violations():
    q = _hero("nutrition").query
    order = nutrition.parse_order(q)
    assert [i.name for i, _ in order] == [
        "Rotisserie-Style Chicken", "Italian Herbs & Cheese bread", "Habanero Jack cheese", "Nashville-Style Hot Sauce",
        "Chipotle Southwest sauce", "crispy onions", "jalapenos", "black olives",
    ]
    assert dict((i.name, m) for i, m in order)["Habanero Jack cheese"] == 2
    a = nutrition.audit(order)
    assert (a["kcal"], a["protein"], a["sodium"]) == (1085, 68, 2680)
    assert len(a["violations"]) == 3  # calories, sodium, dairy (protein passes)
    assert a["dairy_items"] == ["Italian Herbs & Cheese bread", "Habanero Jack cheese", "Chipotle Southwest sauce"]
    assert {"soy", "milk", "egg", "wheat"} <= set(a["allergens"])


def test_nutrition_strict_inequalities_and_other_examples():
    def audit(text):
        return nutrition.audit(nutrition.parse_order(text))
    a = audit("Multigrain bread, Turkey Breast, no cheese, Yellow Mustard, lettuce, tomatoes, spinach")
    assert (a["kcal"], a["protein"], a["sodium"]) == (635, 51, 1890) and len(a["violations"]) == 2
    b = audit("Italian (white) bread, Rotisserie-Style Chicken, Oil & Vinegar, lettuce, tomatoes, spinach, jalapenos")
    assert b["protein"] == 54 and len(b["violations"]) == 1


# --- expected_answer ------------------------------------------------------------------------------------------------
def test_hero_keys_equal_domain_json_answer_keys():
    for d in dom.list_domains():
        exp = _key(d.id)
        assert exp is not None
        want = [(r["label"], r["value"]) for r in d.answer_key["hallucination_trap"]["required"]]
        got = [(r.label, r.value) for r in exp.required]
        assert got[: len(want)] == want or set(want) <= set(got), (d.id, got, want)
        assert [f.pattern for f in exp.forbidden] == [f["pattern"] for f in d.answer_key["hallucination_trap"]["forbidden"]]


def test_hero_expected_values_from_contract():
    vals = lambda d: {r.label: r.value for r in _key(d).required}  # noqa: E731
    assert vals("travel_appr") == {"APPR cash payout": "700.00", "Baggage fee refund": "70.00", "Combined total": "770.00"}
    assert vals("bc_tenancy_cra") == {"Maximum lawful rent increase": "55.20", "Maximum new rent": "2455.20", "CRA TFSA penalty": "135.00"}
    assert vals("b2b_sla") == {"Approved payout": "36000", "Overbilled amount": "9600"}


def test_paraphrase_scores_like_the_hero():
    for d in dom.list_domains():
        p = d.presets[0]
        assert [r.value for r in _key(d.id, p.paraphrase).required] == [r.value for r in _key(d.id).required]


def test_edited_prompt_recomputes_the_key():
    q = _hero("travel_appr").query.replace("6.5 hours", "9.5 hours")
    assert _key("travel_appr", q).required[0].value == "1000.00"
    q = _hero("bc_tenancy_cra").query.replace("$2,400/month", "$3,000/month").replace("$4,500", "$1,000")
    assert [r.value for r in _key("bc_tenancy_cra", q).required] == ["69.00", "3069.00", "30.00"]
    q = _hero("b2b_sla").query.replace("99.62%", "99.95%")
    assert _key("b2b_sla", q).required[0].value == "48000"


def test_key_does_not_apply_when_prompt_no_longer_matches():
    assert _key("travel_appr", "What is the weather in Toronto?") is None
    assert _key("travel_appr", _hero("travel_appr").query.replace("6.5 hours", "1 hours")) is None
    assert _key("nutrition", "How many calories in a salad?") is None
    assert _key("b2b_sla", "Summarise the SLA.") is None
    assert dom.expected_answer("b2b_sla", "tier1_router", "an edited triage ticket") is None
    assert dom.expected_answer("nope", "hallucination_trap", "x") is None
    v = dom.check_answer("anything 700.00", None)
    assert v.key_applies is False and v.correct is False


def test_static_keys_apply_to_preset_text_only():
    for d in dom.list_domains():
        for p in d.presets[1:]:
            assert dom.expected_answer(d.id, p.kind, p.query) is not None
            assert dom.expected_answer(d.id, p.kind, p.query + " also something else") is None


# --- check_answer ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("v,text,ok", [
    ("700.00", "You are owed $700.", True), ("700.00", "CAD 700.00 in total", True), ("700.00", "$1,700", False),
    ("700.00", "7000", False), ("55.20", "2,455.20 is the max", False), ("55.20", "increase of $55.2", True),
    ("2455.20", "new rent $2,455.20.", True), ("36000", "payout of $36,000", True), ("36000", "136,000", False),
    ("1%", "1% per month", True), ("RTB-7", "use form rtb-7", True), ("2|two", "two free bags", True),
])
def test_value_matching(v, text, ok):
    assert value_found(v, text) is ok


def test_number_pattern_rejects_embedding_in_larger_numbers():
    import re

    assert re.search(number_pattern("135.00"), "penalty is $135.")
    assert not re.search(number_pattern("135.00"), "penalty is $1,135.00")
    assert not re.search(number_pattern("135.00"), "penalty is 135.55")


# Recorded Llama-style WRONG answers (the failure modes the demo exists to show) and RIGHT answers.
WRONG = {
    "travel_appr": (
        "Under EU261 you are entitled to €600 for a delay of this length, so the gate agent is right. EU261 applies "
        "to your flight and the $300 voucher is only an alternative. The bags: 2 x $35 = $70 refund. Total: €600 + $70."
    ),
    "bc_tenancy_cra": (
        "The maximum allowable rent increase in BC is 3.0%, which is $72, so the new rent could be $2,472. The 6% "
        "increase of $2,544 is slightly too high. The cousin eviction with 2 months' notice is allowed. The TFSA "
        "penalty is 1% of $4,500 = $45."
    ),
    "nutrition": (
        "Total calories: 890 kcal, protein 62 g and sodium 1,650 mg. This order meets all of your diet rules and is "
        "dairy-free, since sauces rarely contain dairy. There are no violations."
    ),
    "b2b_sla": (
        "The invoice looks correct. The 10% credit tier is correct for 99.62% uptime, so the credit of $4,800 is "
        "right. Premium Support is a valid add-on charge. The $45,600 total is accurate."
    ),
}
RIGHT = {
    "travel_appr": (
        "Your cash payout is CAD 700.00 (6 to 9 hour band, large carrier). The agent was wrong to cite EU261 and "
        "not the €600 figure: it does not apply to a Canadian domestic flight, and a voucher is not mandatory. "
        "Baggage fee refund: 2 x 35 = CAD 70.00. Total: CAD 770.00."
    ),
    "bc_tenancy_cra": (
        "The 2026 cap is 2.3%, not the 3.0% of 2025, so the maximum increase is $55.20 and the maximum new rent is "
        "$2,455.20; 6% is unlawful. A cousin is not close family and 4 months' notice is needed. The TFSA "
        "penalty is $4,500 x 1% x 3 = $135.00."
    ),
    "nutrition": (
        "Totals: 1,085 kcal (over 950), 68 g protein (passes), 2,680 mg sodium (over 1,800). Dairy: the Italian Herbs "
        "& Cheese bread, the Habanero Jack cheese and the Chipotle Southwest sauce contain milk, so it is not dairy-free."
    ),
    "b2b_sla": (
        "99.62% uptime is in the 25% tier, so the credit is $12,000, not the 10% ($4,800). Premium Support is included "
        "at no charge. The approved payout is $36,000, so the invoice is overbilled by $9,600."
    ),
}


@pytest.mark.parametrize("domain", ["travel_appr", "bc_tenancy_cra", "nutrition", "b2b_sla"])
def test_forbidden_patterns_hit_recorded_wrong_answer(domain):
    v = dom.check_answer(WRONG[domain], _key(domain))
    assert v.key_applies and not v.correct
    assert v.forbidden_hits, domain
    for h in v.forbidden_hits:
        s, e = h["span"]
        assert 0 <= s < e <= len(WRONG[domain])
    assert any(not r["found"] for r in v.required)


@pytest.mark.parametrize("domain", ["travel_appr", "bc_tenancy_cra", "nutrition", "b2b_sla"])
def test_right_answer_is_correct_and_rebuttals_do_not_hit(domain):
    v = dom.check_answer(RIGHT[domain], _key(domain))
    assert v.forbidden_hits == [], v.forbidden_hits
    assert v.correct, v.required


def test_card_dict_scoring_ignores_rejected_claims():
    card = {
        "kind": "appr_claim", "delay_compensation_cad": 700.0, "baggage_refund_cad": 70.0, "total_cad": 770.0,
        "rejected_claims": [{"claim": "EU261 applies for €600", "reason": "EU261 does not apply"}],
        "citations": ["appr_compensation_schedule#0"],
    }
    v = dom.check_answer(card, _key("travel_appr"))
    assert v.correct and v.forbidden_hits == []
    assert v.to_dict().keys() == {"correct", "required", "forbidden_hits", "key_applies"}
    bad = {**card, "total_cad": 600.0, "note": "EU261 applies"}
    v = dom.check_answer(bad, _key("travel_appr"))
    assert not v.correct and v.forbidden_hits and v.forbidden_hits[0]["span"] is None


# Recorded from a live openai/gpt-oss-120b run (typographic spaces/hyphens, rebuttal AFTER the figures).
_LIVE_CORRECT_APPR = (
    "**Mandatory cash payout per passenger:** **CAD\u202f$700**  \n\n"
    "(The gate agent\u2019s reference to EU\u202f261 and a \u20ac600/\u200b$300 voucher is irrelevant \u2013 EU\u202f261 does not "
    "apply to a domestic Canada\u2011only flight.)\n\nBaggage refund: 2 \u00d7 $35 = **$70**. Total: **CAD\u202f$770**."
)
_WRONG_APPR = (
    "Since your flight was held up for more than 3 hours, EU261 applies and entitles you to \u20ac600 in compensation, "
    "so the gate agent was right. The $300 voucher is just the airline's cheaper alternative, so push for the cash.\n\n"
    "Total: roughly \u20ac600 + $70 (about $970 CAD)."
)


def test_correct_live_answer_that_rebuts_the_traps_is_not_flagged():
    from app.domains import expected_answer, check_answer
    from tests.heroes import TRAVEL_HERO

    exp = expected_answer("travel_appr", "hallucination_trap", TRAVEL_HERO)
    verdict = check_answer(_LIVE_CORRECT_APPR, exp)
    assert verdict.forbidden_hits == [] and verdict.correct


def test_wrong_answer_that_asserts_the_traps_is_still_flagged():
    from app.domains import expected_answer, check_answer
    from tests.heroes import TRAVEL_HERO

    exp = expected_answer("travel_appr", "hallucination_trap", TRAVEL_HERO)
    verdict = check_answer(_WRONG_APPR, exp)
    assert not verdict.correct and verdict.forbidden_hits
