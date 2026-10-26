# DualSight: Naive AI vs. Nathan's Engineered AI

Two AI assistants get the same question at the same time. On the left is a typical AI chatbot. On the right is **Nathan's Engineered AI**, the same model inside a pipeline that looks things up, checks its own work and refuses to make up numbers. You watch both answer live and see which one is right, how long each took and what each cost.

**Try it: [aegis-ai-race.vercel.app](https://aegis-ai-race.vercel.app/)** · or start the [guided tour](https://aegis-ai-race.vercel.app/?tour=1)

![The hallucination trap: the typical AI approves an overbilled invoice; the engineered AI catches the $9,600 overcharge](docs/hallucination-trap.png)

## What you'll see

Pick one of four example knowledge bases, then click a challenge. Each challenge shows one way ordinary AI assistants go wrong:

| Challenge | Typical AI (left) | Nathan's Engineered AI (right) |
|---|---|---|
| **The hallucination trap.** A question with a tempting wrong answer, such as an overbilled invoice or a gate agent quoting the wrong law | Answers confidently and gets the money wrong | Looks up the actual rules, catches its own mistakes before you see them, and shows its working |
| **The repeat question.** The same question asked again in different words | Pays full price and makes you wait again | Recognises the question and answers instantly for $0.00, but not if a number in it has changed |
| **The simple lookup.** A one-line factual question | Uses the biggest, most expensive model anyway | Sends easy questions to a smaller model at about 1/15 of the price |
| **The hidden attack.** A question with "ignore your instructions…" slipped in | Follows the attacker's instructions | Strips out the attack and answers the real question |

The four knowledge bases are: Air Canada flight-delay compensation, BC renting and Canadian tax-free savings rules, restaurant nutrition and allergens (illustrative numbers), and business contract and invoice audits. Each one contains deliberate traps, such as an expired promotion, an outdated contract or another province's rules, which a careless answer will quote.

**Every answer can be checked.** Each source on the engineered answer is clickable. It opens the original document and highlights the exact passage the answer relied on.

**Pitch mode** (the ▶ button, or the tour link above) plays a captioned walkthrough: the trap, the verdict, the repeat question and the attack, ending on a scoreboard that ranks the two sides by **cost per correct answer**.

## Why it matters for a business

| | |
|---|---|
| **Answers you can audit** | Every answer cites its sources, so finance, compliance or support staff can verify it in one click. |
| **Fewer costly mistakes** | The engineered side checks every figure against your documents before answering, and it won't quote expired or superseded policies. |
| **Pay for right answers** | Repeat questions are free, easy questions go to a cheaper model, and the scoreboard counts money spent on wrong answers as waste. |
| **Works on your documents as they are** | No model training. Update a policy and the next answer uses it. |

The retrieval layer is called **DualSight** because it reads your documents two ways at once: an **exact lens** (keywords such as invoice numbers, form names and amounts) and a **meaning lens** (questions phrased in everyday words). Each passage it uses is labelled with the lens that found it.

![DualSight Retrieval](docs/dualsight.png)

## What I measured

All numbers below can be reproduced with one command each (see [Evaluation](#evaluation)).

- **Finding the right passage.** On 51 test questions, combining both lenses put the right passage first 73% of the time, against 67% for either lens alone. The gain is real but small on a set this size, and the details below say so.
- **Correct answers with a real AI model.** On the invoice-audit trap, with the same AI model on both sides, the typical AI got the money right 3 times out of 10 and Nathan's Engineered AI 9 out of 10, at a 37% lower median cost per question. It was also right 15 out of 15 times on the other three knowledge bases. (Before a fix found by this test, the engineered side got the invoice right only 1 time in 4.)
- **Not reusing stale answers.** Changing a single number in a question (1 passenger → 3) barely changes how "similar" an AI model thinks two questions are. Without a safeguard, 68% of these edited questions would have been answered from memory with the old, wrong answer. A check that the numbers match cut that to 23%, without losing any genuine repeat-question savings.
- **Honest costs.** On the hardest question the engineered side is slower and costs more, because it looks things up and re-checks itself. That is why the scoreboard ranks by cost per *correct* answer rather than raw cost.

---

# For developers

## Architecture

```mermaid
flowchart LR
  subgraph Browser["Next.js (App Router, Tailwind, Framer Motion)"]
    UI[Split-screen race UI]
  end
  subgraph API["FastAPI"]
    N["POST /api/race/naive<br/>(SSE)"]
    E["POST /api/race/engineered<br/>(SSE)"]
  end
  UI -- "fetch + ReadableStream" --> N
  UI -- "fetch + ReadableStream" --> E
  N --> LLM[("Groq LLM<br/>or simulator")]
  E --> G
  subgraph G["LangGraph state machine"]
    direction LR
    R[Guardrail +<br/>Semantic Router] --> C{Semantic<br/>Cache}
    C -- HIT --> V
    C -- MISS --> H[DualSight Retrieval<br/>BM25 + dense, RRF] --> GEN[Generator<br/>8B or 70B] --> K[Hallucination<br/>Critic]
    K -- "ungrounded (max 1 retry)" --> GEN
    K -- grounded --> V[Pydantic<br/>Validator + RAG-triad eval]
  end
  C <--> RD[("Redis<br/>or in-memory NumPy")]
  H <--> VS[("pgvector<br/>or local NumPy index")]
  H --- KB[("Corpus: 4 domains,<br/>SLAs, policies, regulations")]
```

Stack: FastAPI, LangGraph, Pydantic v2, `fastembed` (ONNX, CPU), `rank_bm25`, Groq (OpenAI-compatible streaming API) on the backend; Next.js 15, TypeScript, Tailwind and Framer Motion on the frontend. Deployed on Vercel (frontend) and Render (backend, Docker).

### How each part works

- **Guardrail.** Scans the query for prompt-injection patterns ("ignore previous instructions", "reveal your system prompt") and strips those sentences before anything else sees them.
- **Router.** Scores complexity from length, reasoning keywords, numeric density, "simple task" cues and embedding similarity to complex/simple prototypes. It picks the 8B or 70B tier and the output card type.
- **Semantic cache.** Normalised query embeddings, cosine similarity ≥ 0.92, plus a **figure guard**: a hit is reused only if both queries contain the same numbers (`app/rag/cache.py`, `figures_match`). It uses Redis when `REDIS_URL` is reachable, otherwise an in-memory NumPy fallback with identical behaviour. Entries are namespaced per corpus version, domain and visitor session, so one visitor never pre-warms another's demo.
- **DualSight Retrieval (hybrid RAG).** `BAAI/bge-small-en-v1.5` (quantised ONNX) for dense search plus BM25, fused with **Reciprocal Rank Fusion** (k = 60). Long multi-part questions are also split into sentences and clauses, each searched on its own, and every ranking is fused, with each sub-query's best passage guaranteed a slot. That is what lets the invoice audit retrieve both the SLA clauses *and* the audit policy.
- **Critic.** A deterministic, offline grounding check, with no extra LLM call. Every dollar amount must be derivable from the retrieved text or the question in at most two arithmetic steps, and every percentage must appear literally. Unsupported figures, uncited chunk ids or schema errors send the draft back to the generator once, with feedback.
- **Validation.** Pydantic v2 cards with cross-field checks. For example, an invoice card's findings must each equal billed − expected, the total discrepancy must equal their sum, the approved payout must equal billed total − discrepancy, and the verdict must match the sign.
- **Verdicts are rule-checked, not LLM-judged.** Per-domain calculators and answer keys (`backend/app/domains/`) score both sides against the correct figures and a list of forbidden ones (such as EU261's €600 or the superseded 10% credit tier).
- **Resilience and parity.** Both sides of a race share one provider decision (`race_id`). Groq 429s and 5xx errors are retried with backoff that honours `retry-after`, budgeted per model from Groq's rate-limit headers. If Groq still fails, the *whole race* falls back to the deterministic simulator (a visible **DEMO** badge) and is excluded from the scoreboard, so a live-vs-demo split is never presented as a fair comparison.

## Evaluation

Each evaluation is a script you can rerun, and the first two are enforced in CI by tests.

### Retrieval: is fusing two retrievers better than one?

`python -m app.eval.retrieval` runs **51 labeled questions** ([`backend/data/eval/retrieval_qa.json`](backend/data/eval/retrieval_qa.json)), none of them the demo's preset prompts. 24 are **lexical** (they reuse corpus terms such as "RTB-7" or "SOC 2 Type II") and 27 are **paraphrases** that avoid them. A retrieved chunk is relevant when it contains the labeled fact.

| Configuration | hit@1 | hit@4 | MRR@10 | MRR, lexical | MRR, paraphrase |
|---|---:|---:|---:|---:|---:|
| BM25 only (exact lens) | 0.67 | 0.92 | 0.777 | **0.903** | 0.665 |
| Dense only (meaning lens) | 0.67 | **0.96** | 0.794 | 0.854 | 0.740 |
| Hybrid, RRF | **0.73** | 0.94 | 0.820 | 0.875 | 0.771 |
| Hybrid + sub-queries (shipped) | **0.73** | 0.94 | **0.822** | 0.875 | **0.774** |

- **Each lens fails where you'd expect.** BM25 is best on lexical questions and worst on paraphrases; dense search is the reverse. Fusion has the best hit@1 and MRR overall.
- **The gain is not statistically significant at n = 51.** Paired bootstrap 95% intervals for the MRR difference are +0.045 [−0.025, +0.119] vs BM25 and +0.028 [−0.025, +0.081] vs dense.
- **Dense alone has the best hit@4.** On paraphrases, fusion sometimes lets a keyword-matching but wrong passage push the right one out. I haven't tuned RRF weights to fix this, because tuning on the evaluation set would overfit it.
- **hit@4 is an easy bar** with 12–14 chunks per domain; hit@1 and MRR are the meaningful metrics. I also wrote the questions after reading the corpus, so wording bias is possible.

`tests/test_retrieval_eval.py` fails CI if the shipped configuration drops below hit@4 0.90 or MRR 0.78, or ranks worse than either lens alone. Full output: [`docs/retrieval-eval.md`](docs/retrieval-eval.md).

### Semantic cache: what threshold, and is a threshold enough?

`python -m app.eval.cache_threshold` scores **39 query pairs** ([`backend/data/eval/cache_pairs.json`](backend/data/eval/cache_pairs.json)): 17 rewordings, where reusing the cached answer is right, and 22 near-misses, where the correct answer changes, such as an edited prompt or a 6-hour vs 9-hour delay.

| Threshold | Rewordings reused | Near-misses wrongly reused (cosine only) | Near-misses wrongly reused (+ figure guard) |
|---:|---:|---:|---:|
| 0.85 | 82% | 77% | 32% |
| 0.90 | 82% | 68% | 23% |
| **0.92 (shipped)** | 59% | 68% | **23%** |
| 0.95 | 29% | 55% | 18% |
| 0.98 | 24% | 36% | 9% |

- **No threshold separates the two groups.** Editing one number in a long prompt (99.62% → 99.92% uptime, 1 → 3 passengers) leaves cosine similarity at 0.997–1.000, because sentence embeddings barely encode numbers. Without the guard, a visitor who edits a figure and re-runs could be served the previous answer.
- **The figure guard removes every number-only near-miss** at no cost to legitimate reuse. The near-misses that remain all change a word: "international" → "domestic", "large" → "small carrier", "double cheese" → "no cheese".
- **0.92 stays.** The data suggests 0.90 would reuse more rewordings with the same false-hit rate. But 17 positive pairs is a small sample, and a stale answer costs more than a cache miss, so I kept the more conservative value.

`tests/test_presets_e2e.py` checks end to end that an edited figure is a cache miss with the reason `different figures`. Full table and every pair: [`docs/cache-threshold.md`](docs/cache-threshold.md).

### Live accuracy with Groq

`python scripts/live_accuracy.py` races each domain's hallucination trap repeatedly against a running backend and tallies the server's answer-key verdicts. Races that fell back to the simulator are excluded.

Model `openai/gpt-oss-120b` on a free-tier Groq key, 2026-10-26; no run fell back. Full write-up, root cause and raw logs: [`docs/live-accuracy.md`](docs/live-accuracy.md).

| Knowledge base | Side | Correct | 95% CI (Wilson) | Median cost |
|---|---|---:|---:|---:|
| B2B invoice audit | naive (whole KB in the prompt) | 3/10 | 0.11–0.60 | $0.0572 |
| B2B invoice audit | engineered | **9/10** | 0.60–0.98 | $0.0358 |
| Travel, tenancy + tax, nutrition | engineered | **15/15** | 0.80–1.00 | $0.029–0.041 |

- **The test found a real bug.** Before this run, the engineered side was right on the invoice trap only 1 time in 4. The answer key needs the approved payout ($36,000), but the invoice card had no field for it. Demo mode always passed only because the simulator happened to write that figure into a line item. The card now has `billed_total_usd` and `approved_payout_usd`, validated as payout = billed total − discrepancy.
- **It also found the live site wasn't live.** The deployed backend asked Groq for Llama 3.x models that current keys can't access, so every visitor got the demo simulator. The defaults are now the gpt-oss models measured here.
- **Caveats.** The samples are small and the intervals wide. With a strong model and the whole knowledge base in its prompt, the naive side sometimes gets it right.

### Latency and cost (demo mode)

`python backend/scripts/bench.py` against a local backend in demo mode (simulated LLM pacing; real retrieval, caching and validation). Costs assume a flat $15 per million tokens, with the 8B tier at 1/15 of that.

| Challenge | Naive time | Engineered time | Naive cost | Engineered cost | Engineered tier |
|---|---:|---:|---:|---:|:--:|
| The Hallucination Trap | 3.93 s | 6.64 s | $0.0031 | $0.0334 | 70B |
| The Semantic Cache Race | 3.56 s | 0.46 s | $0.0017 | $0.0005 | 8B |
| Simple Tier-1 Triage | 3.81 s | 0.40 s | $0.0021 | $0.0006 | 8B |
| Adversarial Injection | 2.55 s | 0.48 s | $0.0016 | $0.0005 | 8B |

Semantic cache over 20 runs: miss median 470 ms; **hit median 7.3 ms, p95 7.9 ms, $0.00**. On the hallucination trap the engineered side is slower and about 10× more expensive (retrieval plus a critic retry on the 70B tier). The wins come from caching and routing. Retrieval latency on a throttled CPU is profiled in [`docs/benchmarks.md`](docs/benchmarks.md).

## Run it locally

Requirements: Python 3.11–3.12 (3.14 lacks `onnxruntime` wheels) and Node 20+. Everything works without an API key, in demo mode.

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --port 8000                          # first start downloads the ~130 MB embedding model

# Frontend (second terminal)
cd frontend
npm install
npm run dev                                               # http://localhost:3000
```

Or with Docker:

```bash
docker compose up --build                                                        # http://localhost:3000
REDIS_URL=redis://redis:6379/0 docker compose --profile redis up --build         # Redis semantic cache
DATABASE_URL=postgresql://aegis:aegis@pgvector:5432/aegis \
  docker compose --profile pgvector up --build                                   # pgvector index
```

Copy `.env.example` to `backend/.env` and set `GROQ_API_KEY` for live answers.

**Checks** (all run in CI, along with `pip-audit`, `npm audit` and a Docker build with a container smoke test):

```bash
cd backend  && ruff check . && pytest                # 298 tests; real-embedding tests skip if the model can't load
cd frontend && npm run lint && npx tsc --noEmit && npm test && npm run build    # 52 tests
```

**Evaluations** (from `backend/`):

```bash
python -m app.eval.retrieval                         # retrieval ablation
python -m app.eval.cache_threshold                   # cache threshold sweep
python scripts/live_accuracy.py --help               # live accuracy (needs a running backend with GROQ_API_KEY)
python scripts/bench.py                              # latency and cost
```

### Configuration

| Variable | Where | Purpose |
|---|---|---|
| `GROQ_API_KEY` | backend | Live LLM output; absent = demo mode |
| `GROQ_HEAVY_MODEL` / `GROQ_FAST_MODEL` | backend | Groq model ids for the large and small tiers (default `openai/gpt-oss-120b` / `openai/gpt-oss-20b`; any Groq chat model your key can access) |
| `CORS_ORIGINS` | backend | Comma-separated allowed browser origins |
| `TRUST_PROXY` | backend | `1` to honour `X-Forwarded-For` behind a proxy you control (Render) |
| `RATE_LIMIT_PER_MIN` / `RATE_LIMIT_LIVE_PER_MIN` | backend | Per-client limits on races (default 30) and on live Groq races (default 6; beyond it, races run in demo mode) |
| `REDIS_URL` | backend | Semantic cache in Redis; absent or unreachable = in-memory |
| `DATABASE_URL` | backend | pgvector index; absent or unreachable = local NumPy index |
| `NEXT_PUBLIC_API_URL` | frontend (build time) | Backend URL as seen by the visitor's browser |

If races fall back with `upstream_error`, check which models your key can use at `https://api.groq.com/openai/v1/models`. The panel chip in the UI shows the exact model that ran.

## Deploy: Vercel + Render

Both services deploy automatically on every push to `main`. The browser calls the backend directly, because a proxy in between (such as a Next.js rewrite) would buffer the streamed responses.

**Backend on Render**
1. Create a **Web Service** from this GitHub repo, with **Root Directory** `backend` and the **Docker** runtime. The image bakes in the embedding model and prebuilt indexes, so there is no download at startup.
2. Set `GROQ_API_KEY`, `CORS_ORIGINS=https://aegis-ai-race.vercel.app` and `TRUST_PROXY=1`. Optionally set `GROQ_HEAVY_MODEL` / `GROQ_FAST_MODEL`.
3. Set the health check path to `/api/health`; it reports `ready` once the indexes are warm.

One instance keeps the semantic cache and rate limiter in memory. To run more than one, point `REDIS_URL` at a hosted Redis. On Render's free plan the service sleeps when idle, so the first request after a quiet spell is slow.

**Frontend on Vercel**
1. Import the repo with **Root Directory** `frontend`.
2. Set `NEXT_PUBLIC_API_URL=https://aegis-ai-race-api.onrender.com`. It is inlined at build time, so redeploy after changing it.

**Embedding on another site.** `?embed=true` hides the header and footer and posts the page height to the parent window:

```html
<iframe src="https://aegis-ai-race.vercel.app/?embed=true" style="width:100%;border:0;height:900px" loading="lazy"></iframe>
<script>
  addEventListener("message", (e) => {
    if (e.data?.type === "aegis:resize") document.querySelector("iframe").style.height = e.data.height + "px";
  });
</script>
```

## Streaming API

`POST /api/race/{naive|engineered}` returns `text/event-stream`. Every payload carries `run_id`, `side` and `t_ms`. A stream always ends with `done` or `error`, and a `: ping` heartbeat is sent every 15 s.

| Event | Side | Meaning |
|---|---|---|
| `meta` | both | `mode` (`live`/`demo`), model, fallback reason |
| `node_start` / `node_end` | engineered | `router`, `cache`, `retriever`, `generator`, `critic`, `validator`, with `latency_ms`, `status` and typed `data` |
| `token` | both | Batched text delta, running tokens and cost; `reset` on a retry |
| `card` / `eval` | engineered | Validated structured card with its cited passages; RAG-triad scores |
| `naive_analysis` | naive | Character spans of ungrounded claims |
| `verdict` | both | Answer-key result: required figures found, forbidden figures quoted |
| `fallback` | both | Live → demo switch |
| `done` / `error` | both | Totals, usage, `cache_hit`, `hallucination_prevented` |

Other endpoints: `GET /api/health`, `/api/config`, `/api/presets`, `/api/kb/documents[/{id}]`, `POST /api/cache/reset`.

## Repository layout

```
backend/
  app/rag/         embeddings, BM25, hybrid retriever, semantic cache, vector index
  app/pipeline/    LangGraph nodes, guardrails, naive baseline, SSE streaming
  app/llm/         Groq client, rate-limit-aware gateway, simulator
  app/domains/     per-domain answer keys and calculators
  app/eval/        grounding critic, RAG triad, retrieval and cache evaluations
  data/corpus/     the four knowledge bases;  data/eval/  labeled evaluation sets
  scripts/         bench.py, live_accuracy.py, profile_retrieval.py
  tests/
frontend/src/      components/, lib/ (SSE parser, reducers, pitch copy in brand.ts), __tests__/
docs/              evaluation reports, benchmarks, security notes, design contract, screenshots
```

Security notes: [`docs/security.md`](docs/security.md). Design contract: [`docs/contract-v2.md`](docs/contract-v2.md).

## Known limitations

- The knowledge bases are small and synthetic (6–8 documents, 12–14 chunks each). Invoice figures and nutrition values are made up for the demo.
- The critic checks numbers and citations deterministically; it is not an LLM judge and will not catch subtle errors in free text.
- The cache's figure guard catches changed numbers but not changed words ("international" vs "domestic"). See the cache evaluation.
- In live mode, token counts come from the provider; in demo mode they are estimates (~4 characters per token) and are shown with a `~`.
- `npm audit` reports advisories in the PostCSS copy bundled with Next 15. The only fix offered is the Next 16 upgrade, and they concern processing attacker-controlled CSS at build time, which this app does not do.
