"""Hybrid retrieval: dense + BM25 fused with Reciprocal Rank Fusion."""
from dataclasses import dataclass

from app.rag.bm25 import BM25Index
from app.rag.corpus import Chunk
from app.rag.embeddings import Embedder
from app.rag.vector_index import VectorIndex, make_vector_index

RRF_K = 60


def rrf_fuse(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """score(d) = sum over rankers of 1 / (k + rank(d)), rank starting at 1."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank)
    return scores


@dataclass
class Hit:
    chunk: Chunk
    rrf_score: float
    dense_score: float | None
    bm25_score: float | None
    rank: int


class HybridRetriever:
    def __init__(self, chunks: list[Chunk], embedder: Embedder, vector_index: VectorIndex):
        self.chunks = chunks
        self.embedder = embedder
        self.vector_index = vector_index
        self.bm25 = BM25Index([c.text for c in chunks])

    def retrieve(self, query: str, k: int = 4, candidates: int = 10, mode: str = "hybrid") -> list[Hit]:
        """mode: "hybrid" | "dense" | "bm25" (the single-ranker modes exist for evaluation)."""
        qvec = self.embedder.embed([query])[0]
        dense = dict(self.vector_index.search(qvec, candidates)) if mode in ("hybrid", "dense") else {}
        lexical = dict(self.bm25.search(query, candidates)) if mode in ("hybrid", "bm25") else {}
        rankings = [sorted(dense, key=lambda i: -dense[i]), sorted(lexical, key=lambda i: -lexical[i])]
        fused = rrf_fuse([r for r in rankings if r])
        top = sorted(fused, key=lambda i: -fused[i])[:k]
        return [
            Hit(self.chunks[i], fused[i], dense.get(i), lexical.get(i), rank)
            for rank, i in enumerate(top, start=1)
        ]


def build_retriever(settings, embedder: Embedder, chunks: list[Chunk]) -> HybridRetriever:
    index = make_vector_index(settings, embedder, [c.text for c in chunks])
    return HybridRetriever(chunks, embedder, index)
