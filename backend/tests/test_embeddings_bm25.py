import numpy as np
import pytest

from app.rag.bm25 import BM25Index, tokenize
from app.rag.embeddings import HashingEmbedder


def test_hashing_embedder_is_normalised_and_deterministic(embedder):
    a = embedder.embed(["service credit tiers", "service credit tiers"])
    assert a.shape == (2, embedder.dim)
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0, atol=1e-5)
    assert np.allclose(a[0], a[1])
    assert np.allclose(HashingEmbedder().embed(["service credit tiers"])[0], a[0])


def test_similar_text_scores_higher_than_unrelated(embedder):
    q, near, far = embedder.embed(
        ["uptime service credit percentage", "service credit for uptime", "overtime pay hours"]
    )
    assert q @ near > q @ far


def test_tokenizer_keeps_decimals():
    assert "99.95" in tokenize("Uptime of 99.95%")


def test_bm25_finds_exact_term(chunks):
    idx = BM25Index([c.text for c in chunks])
    top = idx.search("Premium Support separate line item", 3)
    assert top
    assert chunks[top[0][0]].doc_id == "vendor_sla_northwind_cloud"


def test_bm25_empty_query_returns_nothing(chunks):
    assert BM25Index([c.text for c in chunks]).search("the of", 3) == []


@pytest.mark.model
def test_real_fastembed_model_is_semantic():
    from app.rag.embeddings import FastEmbedder

    e = FastEmbedder()
    assert e.dim == 384
    texts = ["How do I reset my password?", "I forgot my password, how can I reset it", "Quarterly revenue"]
    a, b, c = e.embed(texts)
    assert a @ b > 0.8 > a @ c
