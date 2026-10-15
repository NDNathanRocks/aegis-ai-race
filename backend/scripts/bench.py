"""Benchmark the four presets against a running backend and print a Markdown report.

    python scripts/bench.py [--url http://localhost:8000] [--hits 20]

Numbers are the server's own `done.total_ms` / `usage` values, so they exclude browser and network time.
In demo mode (no GROQ_API_KEY) LLM pacing is simulated; retrieval, caching and validation timings are real.
"""
import argparse
import json
import statistics
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.presets import PRESETS  # noqa: E402


def race(client: httpx.Client, side: str, query: str, preset_id: str, session: str, variant: str = "primary") -> dict:
    body = {"query": query, "preset_id": preset_id, "session_id": session, "variant": variant}
    done: dict = {}
    mode = None
    with client.stream("POST", f"/api/race/{side}", json=body, timeout=60) as r:
        r.raise_for_status()
        name = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:])
                if name == "meta":
                    mode = data["mode"]
                if name == "done":
                    done = data
    return {**done, "mode": mode}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--hits", type=int, default=20)
    args = ap.parse_args()
    with httpx.Client(base_url=args.url) as c:
        cfg = c.get("/api/config").json()
        print(f"# Benchmark\n\nMode: **{cfg['mode']}**, embeddings `{cfg['embedding_model']}`, "
              f"cache `{cfg['cache_backend']}`, vector store `{cfg['vector_backend']}`\n")
        print("| Challenge | Naive time | Engineered time | Naive cost | Engineered cost | Engineered tier | Notes |")
        print("|---|---:|---:|---:|---:|:--:|---|")
        for p in PRESETS.values():
            sid = uuid.uuid4().hex
            n = race(c, "naive", p.query, p.id, sid)
            e = race(c, "engineered", p.query, p.id, sid)
            note = "critic caught & corrected a hallucination" if e["hallucination_prevented"] else ""
            print(f"| {p.title} | {n['total_ms'] / 1000:.2f} s | {e['total_ms'] / 1000:.2f} s | ${n['usage']['cost_usd']:.4f} | "
                  f"${e['usage']['cost_usd']:.4f} | {e['usage']['tier'].upper()} | {note} |")

        cache = PRESETS["semantic_cache"]
        miss, hit, naive2 = [], [], []
        for _ in range(args.hits):
            sid = uuid.uuid4().hex
            miss.append(race(c, "engineered", cache.query, cache.id, sid)["total_ms"])
            h = race(c, "engineered", cache.paraphrase or cache.query, cache.id, sid, "paraphrase")
            assert h["cache_hit"], "paraphrase did not hit the cache"
            hit.append(h["total_ms"])
        naive2.append(race(c, "naive", cache.paraphrase or cache.query, cache.id, uuid.uuid4().hex)["total_ms"])
        hit.sort()
        p95 = hit[max(0, int(len(hit) * 0.95) - 1)]
        print(f"\n**Semantic cache** ({args.hits} runs): MISS median {statistics.median(miss):.0f} ms; "
              f"HIT median **{statistics.median(hit):.1f} ms**, p95 {p95:.1f} ms, cost $0.00; "
              f"naive repeat {naive2[0] / 1000:.2f} s.")


if __name__ == "__main__":
    main()
