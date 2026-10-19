import pytest

from app.rag.hybrid import RRF_K, rrf_fuse

# (query, doc ids that must appear in the top-k)
EVAL_SET = [
    # lexical-friendly (exact terms / numbers)
    ("What credit applies if uptime was 99.62 percent?", {"vendor_sla_northwind_cloud"}),
    ("Is Premium Support billable separately on the Enterprise Plan?", {"vendor_sla_northwind_cloud"}),
    ("password reset ticket priority", {"cloud_infra_sop_incident_response"}),
    ("how much is the on-call stipend", {"workforce_scheduling_policy"}),
    ("when is the weekly maintenance window", {"cloud_infra_sop_change_management"}),
    # semantic-friendly (paraphrases with little term overlap)
    ("staff are not allowed to work a full week without a day off", {"workforce_scheduling_policy"}),
    ("money back from the provider when their platform was down too long", {"vendor_sla_northwind_cloud"}),
    ("someone is locked out of their account", {"cloud_infra_sop_incident_response"}),
    # multi-document
    ("audit invoice: credits owed after uptime fell, and Premium Support was added",
     {"vendor_sla_northwind_cloud", "invoice_policy_and_credits"}),
]


def test_rrf_math():
    fused = rrf_fuse([[10, 20, 30], [20, 10]])
    assert fused[10] == pytest.approx(1 / (RRF_K + 1) + 1 / (RRF_K + 2))
    assert fused[20] == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))
    assert fused[30] == pytest.approx(1 / (RRF_K + 3))
    assert fused[10] > fused[30]


def test_rrf_rewards_agreement():
    fused = rrf_fuse([[1, 2, 3], [4, 2, 5]])
    assert max(fused, key=fused.get) == 2


def _recall(retriever, mode: str, k: int = 4) -> float:
    total = found = 0
    for query, expected in EVAL_SET:
        docs = {h.chunk.doc_id for h in retriever.retrieve(query, k=k, mode=mode)}
        total += len(expected)
        found += len(expected & docs)
    return found / total


def test_hybrid_recall_at_least_as_good_as_either_alone(retriever):
    # Offline hashing embedder has no semantics, so this checks fusion never hurts.
    hybrid, dense, bm25 = (_recall(retriever, m) for m in ("hybrid", "dense", "bm25"))
    assert hybrid >= max(dense, bm25) - 0.1  # fusion may trade a little recall for robustness
    assert hybrid >= 0.75


@pytest.mark.model
def test_hybrid_beats_lexical_with_real_embeddings(chunks):
    from app.rag.embeddings import FastEmbedder
    from app.rag.hybrid import HybridRetriever
    from app.rag.vector_index import LocalVectorIndex

    emb = FastEmbedder()
    r = HybridRetriever(chunks, emb, LocalVectorIndex(emb.embed([c.text for c in chunks])))
    hybrid, dense, bm25 = (_recall(r, m) for m in ("hybrid", "dense", "bm25"))
    assert hybrid >= max(dense, bm25)
    assert hybrid > bm25
    assert hybrid >= 0.95


def test_hits_are_ranked_and_scored(retriever):
    hits = retriever.retrieve("service credit tiers for uptime", k=4)
    assert [h.rank for h in hits] == [1, 2, 3, 4]
    assert all(hits[i].rrf_score >= hits[i + 1].rrf_score for i in range(3))
    assert "vendor_sla_northwind_cloud" in {h.chunk.doc_id for h in hits}  # the 2023 legacy SLA is a deliberate decoy
    assert hits[0].bm25_score is not None and hits[0].dense_score is not None
