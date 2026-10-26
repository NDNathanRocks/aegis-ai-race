"""Semantic-cache threshold sweep: how often a rewording hits vs how often a different question is wrongly served.

    python -m app.eval.cache_threshold [--out ../docs/cache-threshold.md]

Each labeled pair (data/eval/cache_pairs.json) is embedded with the production model and scored by cosine
similarity, which is exactly what the cache compares. For every threshold t, a pair counts as a cache hit when
cosine >= t: 'same' pairs should hit (hit rate), 'different' pairs must not (false-hit rate).
"""
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from app.config import BACKEND_DIR
from app.rag.cache import figures_match

PAIRS_PATH = BACKEND_DIR / "data" / "eval" / "cache_pairs.json"
THRESHOLDS = [round(0.80 + 0.01 * i, 2) for i in range(19)]  # 0.80 .. 0.98


@dataclass(frozen=True)
class Pair:
    domain: str
    label: str  # "same" | "different"
    a: str
    b: str


def load_pairs(path: Path = PAIRS_PATH) -> list[Pair]:
    from app.domains import get_domain

    out = []
    for p in json.loads(path.read_text(encoding="utf-8"))["pairs"]:
        hero = get_domain(p["domain"]).presets[0]
        named = {"@hero": hero.query, "@paraphrase": hero.paraphrase}
        a = named.get(p["a"], p["a"])
        if "replace" in p:
            old, new = p["replace"]
            if old not in a:
                raise ValueError(f"{old!r} not in the {p['domain']} anchor")
            b = a.replace(old, new)
        else:
            b = named.get(p["b"], p["b"])
        out.append(Pair(p["domain"], p["label"], a, b))
    return out


def cosines(pairs: list[Pair], embedder) -> list[float]:
    vecs = embedder.embed([t for p in pairs for t in (p.a, p.b)])
    return [float(vecs[2 * i] @ vecs[2 * i + 1]) for i in range(len(pairs))]


def sweep(pairs: list[Pair], cos: list[float]) -> list[dict]:
    """Per threshold: hit rates on 'same' and 'different' pairs, by cosine alone and with the figure guard."""


    rows = [(p.label, c, figures_match(p.a, p.b)) for p, c in zip(pairs, cos, strict=True)]
    n_same, n_diff = sum(r[0] == "same" for r in rows), sum(r[0] == "different" for r in rows)

    def rate(label: str, t: float, guard: bool) -> float:
        n = n_same if label == "same" else n_diff
        return sum(lab == label and c >= t and (ok or not guard) for lab, c, ok in rows) / n

    return [
        {"t": t, "hit_rate": rate("same", t, False), "false_hit_rate": rate("different", t, False),
         "guarded_hit_rate": rate("same", t, True), "guarded_false_hit_rate": rate("different", t, True)}
        for t in THRESHOLDS
    ]


def report(pairs: list[Pair], cos: list[float], current: float) -> str:
    n_same = sum(p.label == "same" for p in pairs)
    lines = [f"{len(pairs)} pairs across 4 domains: {n_same} rewordings (should hit), {len(pairs) - n_same} near-misses "
             "whose answer differs (must not hit). Cosine similarity from the production embedding model.", "",
             "| Threshold | Rewordings served (cosine only) | Near-misses wrongly served (cosine only) "
             "| Rewordings served (+ figure guard) | Near-misses wrongly served (+ figure guard) |",
             "|---:|---:|---:|---:|---:|"]
    for row in sweep(pairs, cos):
        mark = " **(current)**" if abs(row["t"] - current) < 1e-9 else ""
        lines.append(f"| {row['t']:.2f}{mark} | {row['hit_rate']:.0%} | {row['false_hit_rate']:.0%} "
                     f"| {row['guarded_hit_rate']:.0%} | {row['guarded_false_hit_rate']:.0%} |")
    lines += ["", "### Every pair, highest similarity first", ""]
    lines += ["| Cosine | Label | Same figures | Domain | Change |", "|---:|---|---|---|---|"]

    for p, c in sorted(zip(pairs, cos, strict=True), key=lambda x: -x[1]):
        lines.append(f"| {c:.3f} | {p.label} | {'yes' if figures_match(p.a, p.b) else 'no'} | {p.domain} | {_describe(p)} |")
    return "\n".join(lines) + "\n"


def _describe(p: Pair) -> str:
    if len(p.a) > 200:  # long hero prompt: show only the edited span
        i = next((k for k, (x, y) in enumerate(zip(p.a, p.b, strict=False)) if x != y), None)
        if i is None:
            return "hero prompt vs its paraphrase"
        return f"hero prompt with `{p.a[i:i + 30].strip()}…` → `{p.b[i:i + 30].strip()}…`"
    return f"{p.a} → {p.b}"


def main() -> None:
    from app.config import Settings
    from app.rag.embeddings import FastEmbedder

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, help="also write the Markdown report to this file")
    args = ap.parse_args()
    settings = Settings(groq_api_key=None, redis_url=None, database_url=None)
    pairs = load_pairs()
    text = report(pairs, cosines(pairs, FastEmbedder(settings.embedding_model)), settings.cache_threshold)
    sys.stdout.reconfigure(encoding="utf-8")  # the Windows console default (cp1252) cannot print the arrows
    print(text)
    if args.out:
        args.out.write_text("# Semantic cache threshold sweep\n\nReproduce: `python -m app.eval.cache_threshold`.\n\n" + text,
                            encoding="utf-8")


if __name__ == "__main__":
    main()
