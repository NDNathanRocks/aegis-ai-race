"""Retrieval ablation: BM25 only vs dense only vs hybrid (RRF), on a labeled question set.

    python -m app.eval.retrieval [--out ../docs/retrieval-eval.md]

A retrieved chunk is relevant when it contains the question's fact string (any of the ' || ' alternatives).
Metrics per configuration: hit@1, hit@2 (the 8B path's k), hit@4 (the 70B path's k) and MRR@10, overall and by
question style, with a paired bootstrap 95% CI for hybrid minus each single lens.
"""
import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path

from app.config import BACKEND_DIR

QA_PATH = BACKEND_DIR / "data" / "eval" / "retrieval_qa.json"
KS = (1, 2, 4)
DEPTH = 10

# (label, mode, decompose). The last one is what the engineered pipeline runs.
CONFIGS = [
    ("BM25 only", "bm25", False),
    ("Dense only", "dense", False),
    ("Hybrid (RRF)", "hybrid", False),
    ("Hybrid + sub-queries", "hybrid", True),
]


@dataclass(frozen=True)
class Question:
    domain: str
    style: str
    query: str
    alternatives: tuple[str, ...]

    def relevant(self, text: str) -> bool:
        return any(a in text for a in self.alternatives)


def load_questions(path: Path = QA_PATH) -> list[Question]:
    raw = json.loads(path.read_text(encoding="utf-8"))["questions"]
    return [Question(q["domain"], q["style"], q["query"], tuple(a.strip() for a in q["fact"].split(" || "))) for q in raw]


def unlabeled(questions: list[Question], chunks_by_domain: dict[str, list]) -> list[Question]:
    """Questions whose fact appears in no chunk of their domain (a broken label, not a retrieval miss)."""
    return [q for q in questions if not any(q.relevant(c.text) for c in chunks_by_domain[q.domain])]


def first_relevant_rank(q: Question, retriever, mode: str, decompose: bool) -> int | None:
    hits = retriever.retrieve(q.query, DEPTH, DEPTH, mode, None, decompose)
    return next((h.rank for h in hits if q.relevant(h.chunk.text)), None)


def summarize(ranks: list[int | None]) -> dict[str, float]:
    n = len(ranks)
    out = {f"hit@{k}": sum(1 for r in ranks if r is not None and r <= k) / n for k in KS}
    out["mrr"] = sum(1 / r for r in ranks if r is not None) / n
    return out


def paired_bootstrap_ci(a: list[float], b: list[float], iters: int = 5000, seed: int = 0) -> tuple[float, float, float]:
    """Mean of a - b with a 95% percentile interval, resampling questions (pairs stay together)."""
    rng = random.Random(seed)
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(iters))
    return sum(diffs) / n, means[int(0.025 * iters)], means[int(0.975 * iters)]


def _rr(r: int | None) -> float:
    return 0.0 if r is None else 1 / r


def run(runtimes: dict, questions: list[Question]) -> dict:
    """Ranks for every (config, question), keyed by config label."""
    return {
        label: [first_relevant_rank(q, runtimes[q.domain].retriever, mode, dec) for q in questions]
        for label, mode, dec in CONFIGS
    }


def report(questions: list[Question], ranks: dict[str, list[int | None]], header: str = "") -> str:
    lines = [header] if header else []
    styles = sorted({q.style for q in questions})
    counts = ", ".join(f"{sum(q.style == s for q in questions)} {s}" for s in styles)
    lines += [f"{len(questions)} questions across {len({q.domain for q in questions})} domains ({counts}).", ""]

    def table(title: str, idx: list[int]) -> None:
        lines.extend([f"### {title} (n = {len(idx)})", ""])
        lines.extend(["| Configuration | hit@1 | hit@2 | hit@4 | MRR@10 |", "|---|---:|---:|---:|---:|"])
        for label, *_ in CONFIGS:
            s = summarize([ranks[label][i] for i in idx])
            lines.append(f"| {label} | {s['hit@1']:.2f} | {s['hit@2']:.2f} | {s['hit@4']:.2f} | {s['mrr']:.3f} |")
        lines.append("")

    table("All questions", list(range(len(questions))))
    for s in styles:
        table(f"{s.capitalize()} questions", [i for i, q in enumerate(questions) if q.style == s])

    best = CONFIGS[-1][0]
    lines += [f"### {best} vs each single lens: MRR difference, paired bootstrap 95% CI", ""]
    for label, *_ in CONFIGS[:2]:
        mean, lo, hi = paired_bootstrap_ci([_rr(r) for r in ranks[best]], [_rr(r) for r in ranks[label]])
        lines.append(f"- vs {label}: {mean:+.3f} [{lo:+.3f}, {hi:+.3f}]")
    misses = [q for q, r in zip(questions, ranks[best], strict=True) if r is None or r > 4]
    lines += ["", f"### Misses at k = 4 for {best} ({len(misses)})", ""]
    lines += [f"- `{q.domain}` ({q.style}): {q.query}" for q in misses] or ["- none"]
    return "\n".join(lines) + "\n"


def main() -> None:
    from app.config import Settings
    from app.domains import build_domains
    from app.rag.embeddings import FastEmbedder

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, help="also write the Markdown report to this file")
    args = ap.parse_args()

    settings = Settings(groq_api_key=None, redis_url=None, database_url=None)
    embedder = FastEmbedder(settings.embedding_model)
    runtimes = build_domains(settings, embedder, warm=False)
    questions = load_questions()
    broken = unlabeled(questions, {d: rt.chunks for d, rt in runtimes.items()})
    if broken:
        raise SystemExit("facts not found in their domain's chunks:\n" + "\n".join(q.query for q in broken))
    header = (
        f"Embeddings `{settings.embedding_model}`, BM25 (`rank_bm25`), RRF k = 60, {DEPTH} candidates per ranker. "
        "Reproduce: `python -m app.eval.retrieval`."
    )
    text = report(questions, run(runtimes, questions), header)
    print(text)
    if args.out:
        args.out.write_text("# Retrieval ablation\n\n" + text, encoding="utf-8")


if __name__ == "__main__":
    main()
