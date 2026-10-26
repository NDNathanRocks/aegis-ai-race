"""Live accuracy: race each domain's hallucination trap N times against a running backend and tally the verdicts.

    python scripts/live_accuracy.py --url http://localhost:8010 --runs 10 [--domains b2b_sla] [--sides engineered] [--pause 45]

On a free Groq key (8,000 tokens/minute) start the backend with GROQ_RETRY_BUDGET_S=60 and RATE_LIMIT_LIVE_PER_MIN=1000
so calls wait for quota instead of falling back, and keep --pause around 45 s.

Both sides of a race run concurrently with a shared race_id, as in the UI. Each run uses a fresh session, so the
semantic cache never answers. The server's own `verdict` event (the deterministic answer key) is the score. Races
that fell back to the simulator (`meta.mode != "live"` or a `fallback` event) are recorded but excluded from the
accuracy figures. One JSON line per side is appended to --log, so an interrupted run keeps its results; --report
re-reads the log and prints the summary without racing.
"""
import argparse
import json
import math
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.domains import DOMAIN_ORDER, get_domain  # noqa: E402


def race_side(url: str, side: str, body: dict) -> dict:
    out = {"side": side, "mode": None, "fallback": False, "correct": None, "missing": [], "forbidden": [], "error": None}
    name = None
    try:
        with httpx.stream("POST", f"{url}/api/race/{side}", json=body, timeout=180) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line.startswith("event:"):
                    name = line[6:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                data = json.loads(line[5:])
                if name == "meta":
                    out["mode"], out["model"] = data.get("mode"), data.get("model")
                elif name == "fallback":
                    out["fallback"], out["fallback_reason"] = True, data.get("reason")
                elif name == "card":
                    out["card"] = data.get("card")  # kept so a miss can be diagnosed from the log
                elif name == "verdict":
                    out["correct"] = data["correct"]
                    out["missing"] = [r["label"] for r in data.get("required", []) if not r.get("found")]
                    out["forbidden"] = [h["label"] for h in data.get("forbidden_hits", [])]
                elif name == "done":
                    out["total_ms"] = data.get("total_ms")
                    out["cost_usd"] = (data.get("usage") or {}).get("cost_usd")
                    out["mode"] = data.get("mode", out["mode"])
                elif name == "error":
                    out["error"] = data.get("message") or data.get("code") or "error"
    except Exception as e:  # network / HTTP errors are recorded, not fatal
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def summarize(rows: list[dict]) -> str:
    lines = ["| Domain | Side | Correct | 95% CI (Wilson) | Excluded (fell back / error) | Median cost |",
             "|---|---|---:|---:|---:|---:|"]
    for domain in DOMAIN_ORDER:
        for side in ("naive", "engineered"):
            rs = [r for r in rows if r["domain"] == domain and r["side"] == side]
            if not rs:
                continue
            ok = [r for r in rs if r["mode"] == "live" and not r["fallback"] and not r["error"] and r["correct"] is not None]
            k, n = sum(r["correct"] for r in ok), len(ok)
            lo, hi = wilson(k, n)
            costs = sorted(r["cost_usd"] for r in ok if r.get("cost_usd") is not None)
            med = f"${costs[len(costs) // 2]:.4f}" if costs else "n/a"
            lines.append(f"| {domain} | {side} | {k}/{n} | {lo:.2f}-{hi:.2f} | {len(rs) - n} | {med} |")
    misses = [r for r in rows if r["side"] == "engineered" and r["mode"] == "live" and r["correct"] is False]
    if misses:
        lines += ["", "Engineered misses (missing required figures / forbidden figures quoted):"]
        lines += [f"- {r['domain']} run {r['run']}: missing {r['missing'] or '-'}; forbidden {r['forbidden'] or '-'}" for r in misses]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://localhost:8010")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--domains", nargs="*", default=list(DOMAIN_ORDER))
    ap.add_argument("--sides", nargs="*", default=["naive", "engineered"], choices=["naive", "engineered"])
    ap.add_argument("--pause", type=float, default=20.0, help="seconds between races (Groq tokens-per-minute budget)")
    ap.add_argument("--log", type=Path, default=Path("live_accuracy.jsonl"))
    ap.add_argument("--report", action="store_true", help="only summarize an existing --log")
    args = ap.parse_args()

    if not args.report:
        with args.log.open("a", encoding="utf-8") as log, ThreadPoolExecutor(2) as pool:
            for run in range(1, args.runs + 1):
                for domain in args.domains:
                    preset = get_domain(domain).presets[0]
                    body = {"query": preset.query, "domain": domain, "preset_id": preset.id,
                            "race_id": uuid.uuid4().hex, "session_id": uuid.uuid4().hex}
                    sides = pool.map(lambda s, b=body: race_side(args.url, s, b), args.sides)
                    for row in sides:
                        row.update(domain=domain, run=run, ts=time.time())
                        log.write(json.dumps(row) + "\n")
                        log.flush()
                        print(f"run {run} {domain:15} {row['side']:10} mode={row['mode']} fb={row['fallback']} "
                              f"correct={row['correct']} err={row['error']}", flush=True)
                    time.sleep(args.pause)
    rows = [json.loads(line) for line in args.log.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(summarize(rows))


if __name__ == "__main__":
    main()
