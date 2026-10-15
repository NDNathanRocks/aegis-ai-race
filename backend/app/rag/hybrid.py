"""Hybrid retrieval: dense + BM25 fused with Reciprocal Rank Fusion."""
import re
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

    def retrieve(
        self,
        query: str,
        k: int = 4,
        candidates: int = 10,
        mode: str = "hybrid",
        qvec=None,
        decompose: bool = False,
    ) -> list[Hit]:
        """mode: "hybrid" | "dense" | "bm25" (the single-ranker modes exist for evaluation).

        Pass `qvec` to reuse an already-computed query embedding. With `decompose`,
        each sentence of a multi-sentence query is also searched on its own and all
        rankings are fused, so a long query dominated by one topic cannot crowd out
        the others."""
        queries = [query] + (split_subqueries(query) if decompose else [])
        vecs = self.embedder.embed(queries) if (qvec is None or len(queries) > 1) else None
        rankings: list[list[int]] = []
        dense_best: dict[int, float] = {}
        bm25_best: dict[int, float] = {}
        for i, q in enumerate(queries):
            v = qvec if (i == 0 and qvec is not None) else vecs[i]
            if mode in ("hybrid", "dense"):
                d = dict(self.vector_index.search(v, candidates))
                rankings.append(sorted(d, key=lambda j: -d[j]))
                for j, sc in d.items():
                    dense_best[j] = max(sc, dense_best.get(j, -1.0))
            if mode in ("hybrid", "bm25"):
                lex = dict(self.bm25.search(q, candidates))
                if lex:
                    rankings.append(sorted(lex, key=lambda j: -lex[j]))
                for j, sc in lex.items():
                    bm25_best[j] = max(sc, bm25_best.get(j, 0.0))
        fused = rrf_fuse([r for r in rankings if r])
        top = sorted(fused, key=lambda j: -fused[j])[:k]
        return [
            Hit(self.chunks[j], fused[j], dense_best.get(j), bm25_best.get(j), rank)
            for rank, j in enumerate(top, start=1)
        ]


_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def split_subqueries(query: str, max_sub: int = 4) -> list[str]:
    """Sentences of a multi-sentence query that are long enough to carry their own topic."""
    parts = [p.strip() for p in _SENTENCE.split(query.strip()) if len(p.split()) >= 4]
    if len(parts) < 2:
        return []
    return list(dict.fromkeys(parts))[:max_sub]


def build_retriever(settings, embedder: Embedder, chunks: list[Chunk]) -> HybridRetriever:
    index = make_vector_index(settings, embedder, [c.text for c in chunks])
    return HybridRetriever(chunks, embedder, index)
