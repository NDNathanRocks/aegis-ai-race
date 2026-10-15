"""RAG Triad evaluator: Faithfulness, Context Relevance, Schema Validity (+ Context Recall)."""
import re

from app.eval.grounding import _content_tokens
from app.presets import Preset
from app.schemas import RetrievedChunk, TriadScores


def context_relevance(query: str, chunks: list[RetrievedChunk]) -> float:
    """Mean per-chunk relevance, where a chunk's relevance is the larger of its
    dense cosine similarity to the query and the fraction of the query's content
    words it contains."""
    if not chunks:
        return 0.0
    q_tokens = _content_tokens(re.sub(r"[\d$%,.]+", " ", query))
    scores = []
    for c in chunks:
        lexical = len(q_tokens & _content_tokens(c.text)) / len(q_tokens) if q_tokens else 0.0
        scores.append(max(c.dense_score or 0.0, lexical))
    return max(0.0, min(1.0, sum(scores) / len(scores)))


def context_recall(preset: Preset | None, chunks: list[RetrievedChunk]) -> float | None:
    """Fraction of the preset's ground-truth facts present in the retrieved context."""
    if not preset or not preset.expected_facts:
        return None
    blob = " ".join(c.text for c in chunks).lower()
    found = sum(1 for f in preset.expected_facts if f.lower() in blob)
    return found / len(preset.expected_facts)


def score_triad(
    *,
    query: str,
    chunks: list[RetrievedChunk],
    faithfulness: float,
    unsupported: list[str],
    schema_valid: bool,
    preset: Preset | None,
) -> TriadScores:
    return TriadScores(
        faithfulness=round(faithfulness, 4),
        context_relevance=round(context_relevance(query, chunks), 4),
        schema_validity=1.0 if schema_valid else 0.0,
        context_recall=context_recall(preset, chunks),
        unsupported_claims=unsupported,
    )
