from decimal import Decimal

from app.eval.grounding import evaluate_grounding, extract_numbers
from app.eval.triad import context_recall, context_relevance, score_triad
from app.presets import PRESETS
from app.schemas import RetrievedChunk

CTX = (
    "Uptime below 99.9% but at or above 99.0%: 25% of the monthly fee. Uptime below 99.95% but at or above "
    "99.9%: 10% of the monthly fee. Premium Support is included at no additional charge."
)
QUERY = "Managed Kubernetes fee is $48,000, uptime 99.62%, 10% credit ($4,800), $2,400 Premium Support. Total billed: $45,600."


def test_extract_numbers_splits_amounts_and_percents():
    n = extract_numbers("fee $48,000, credit 25%, uptime 99.62%, section 4")
    assert Decimal(48000) in n.amounts and {Decimal(25), Decimal("99.62")} == n.percents
    assert not any(a < 100 for a in n.amounts)


def test_derived_values_are_supported():
    # 48,000 * 25% = 12,000; 48,000 - 12,000 = 36,000; 43,200 - 36,000 = 7,200; + 2,400 = 9,600
    payload = {"expected_usd": 36000, "discrepancy_usd": 7200, "total_discrepancy_usd": 9600}
    g = evaluate_grounding(payload, CTX, QUERY)
    assert g.unsupported == [] and g.faithfulness == 1.0


def test_invented_percentage_is_flagged():
    g = evaluate_grounding({"line_item": "credit at the 20% tier"}, CTX, QUERY)
    assert any("20%" in u for u in g.unsupported)
    assert g.faithfulness < 1.0


def test_invented_amount_is_flagged():
    g = evaluate_grounding({"total_discrepancy_usd": 123457}, CTX, QUERY)
    assert any("123,457" in u for u in g.unsupported)


def test_ungrounded_prose_lowers_faithfulness():
    g = evaluate_grounding({"answer": "Zebras migrate across savannas during seasonal droughts."}, CTX, QUERY)
    assert g.faithfulness == 0.0


def _chunk(text, dense=0.8):
    return RetrievedChunk(
        chunk_id="c#1", doc_id="c", doc_title="C", section="s", text=text, rrf_score=0.03, rank=1, dense_score=dense
    )


def test_context_recall_uses_preset_facts():
    p = PRESETS["semantic_cache"]
    assert context_recall(p, [_chunk("... 25% of the monthly fee ...")]) == 1.0
    assert context_recall(p, [_chunk("unrelated")]) == 0.0
    assert context_recall(None, [_chunk("x")]) is None


def test_context_relevance_range():
    assert context_relevance("anything", []) == 0.0
    assert 0.0 <= context_relevance("service credit uptime", [_chunk("service credit for uptime", 0.3)]) <= 1.0


def test_score_triad_schema_validity_is_binary():
    kw = dict(query="q", chunks=[_chunk("t")], faithfulness=0.9, unsupported=[], preset=None)
    assert score_triad(schema_valid=True, **kw).schema_validity == 1.0
    assert score_triad(schema_valid=False, **kw).schema_validity == 0.0
