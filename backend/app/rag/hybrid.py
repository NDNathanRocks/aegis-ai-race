"""Hybrid retrieval: dense + BM25 fused with Reciprocal Rank Fusion."""
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass

from app.rag.bm25 import BM25Index, tokenize
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
        self._hits: OrderedDict[tuple, list[Hit]] = OrderedDict()
        self._hits_lock = threading.Lock()
        self.hits_max = 512

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
        the others.

        Results are memoised per (query, k, candidates, mode, decompose); `qvec` is assumed to be the embedding
        of `query` (as the pipeline passes it), so it is not part of the key."""
        key = (query, k, candidates, mode, decompose)
        with self._hits_lock:
            cached = self._hits.get(key)
            if cached is not None:
                self._hits.move_to_end(key)
                return list(cached)
        hits = self._retrieve(query, k, candidates, mode, qvec, decompose)
        with self._hits_lock:
            self._hits[key] = hits
            while len(self._hits) > self.hits_max:
                self._hits.popitem(last=False)
        return list(hits)

    def _retrieve(self, query: str, k: int, candidates: int, mode: str, qvec, decompose: bool) -> list[Hit]:
        queries = [query] + (split_subqueries(query) if decompose else [])
        vecs = self.embedder.embed(queries) if (qvec is None or len(queries) > 1) else None
        rankings: list[list[int]] = []
        per_query_best: list[int | None] = []
        dense_best: dict[int, float] = {}
        bm25_best: dict[int, float] = {}
        for i, q in enumerate(queries):
            v = qvec if (i == 0 and qvec is not None) else vecs[i]
            local: list[list[int]] = []
            if mode in ("hybrid", "dense"):
                d = dict(self.vector_index.search(v, candidates))
                rankings.append(sorted(d, key=lambda j: -d[j]))
                local.append(rankings[-1])
                for j, sc in d.items():
                    dense_best[j] = max(sc, dense_best.get(j, -1.0))
            if mode in ("hybrid", "bm25"):
                lex = dict(self.bm25.search(q, candidates))
                if lex:
                    rankings.append(sorted(lex, key=lambda j: -lex[j]))
                    local.append(rankings[-1])
                for j, sc in lex.items():
                    bm25_best[j] = max(sc, bm25_best.get(j, 0.0))
            if i > 0 and local:
                lf = rrf_fuse(local)
                per_query_best.append(max(lf, key=lambda j: lf[j]))
        fused = rrf_fuse([r for r in rankings if r])
        ordered = sorted(fused, key=lambda j: -fused[j])
        top = ordered[:k]
        if decompose and len(queries) > 1:
            # Coverage guarantee: each sub-query's own best chunk is kept, so one dominant topic cannot take all k slots.
            guaranteed = []
            for per_query in per_query_best:
                if per_query is not None and per_query not in guaranteed:
                    guaranteed.append(per_query)
            guaranteed.sort(key=lambda j: -fused[j])
            keep = guaranteed[:k]
            top = keep + [j for j in ordered if j not in keep][: k - len(keep)]
            top.sort(key=lambda j: -fused[j])
        return [
            Hit(self.chunks[j], fused[j], dense_best.get(j), bm25_best.get(j), rank)
            for rank, j in enumerate(top, start=1)
        ]


_SENTENCE = re.compile(r"(?<=[.!?])\s+")


_CLAUSE = re.compile(r",\s*(?:and|or|also)?\s+|;\s*|\s+(?:and if|or if|and also)\s+|\s+OR\s+")


def split_subqueries(query: str, max_sub: int = 8) -> list[str]:
    """Sentences of a multi-sentence query, plus the clauses of long sentences, that can carry their own topic.

    Clause fragments of at least 3 words are searched on their own so that a list ("X on Y, double Z, sauce W")
    or a compound question ("payout ..., and if I also paid ...") gets one ranking per facet."""
    parts = [p.strip() for p in _SENTENCE.split(query.strip()) if len(tokenize(p)) >= 4]
    out: list[str] = list(parts)
    for sentence in parts:
        if len(sentence.split()) < 14:
            continue
        for frag in _CLAUSE.split(sentence):
            frag = re.sub(r"^(and|or|also|then)\s+", "", frag.strip(" .?!"), flags=re.I)
            if len(tokenize(frag)) >= 3 and frag != sentence:
                out.append(frag)
    out = list(dict.fromkeys(out))
    if len(out) < 2 and len(parts) < 2:
        return []
    return out[:max_sub]


def build_retriever(settings, embedder: Embedder, chunks: list[Chunk], namespace: str = "") -> HybridRetriever:
    index = make_vector_index(settings, embedder, [c.text for c in chunks], namespace=namespace)
    return HybridRetriever(chunks, embedder, index)
