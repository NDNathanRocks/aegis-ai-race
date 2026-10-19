# Benchmark

Mode: **demo**, embeddings `BAAI/bge-small-en-v1.5`, cache `memory`, vector store `local`

| Challenge | Naive time | Engineered time | Naive cost | Engineered cost | Engineered tier | Notes |
|---|---:|---:|---:|---:|:--:|---|
| The Hallucination Trap | 3.93 s | 6.64 s | $0.0031 | $0.0334 | 70B | critic caught & corrected a hallucination |
| The Semantic Cache Race | 3.56 s | 0.46 s | $0.0017 | $0.0005 | 8B |  |
| Simple Tier-1 Triage | 3.81 s | 0.40 s | $0.0021 | $0.0006 | 8B |  |
| Adversarial Injection | 2.55 s | 0.48 s | $0.0016 | $0.0005 | 8B |  |

**Semantic cache** (20 runs): MISS median 470 ms; HIT median **7.3 ms**, p95 7.9 ms, cost $0.00; naive repeat 3.55 s.


## Retrieval latency profile (v2, Agent 1)

Reproduce: `python backend/scripts/profile_retrieval.py [--threads N] [--throttle CPU] ` (before) and
`... --after --cache-dir <prebuilt dir> [--throttle CPU]` (shipped path). Host: Windows 11, 32 logical cores, fastembed 0.9 / onnxruntime 1.31.
Docker was NOT available on this machine, so `docker run --cpus=0.1` was not run. `--throttle` emulates a CFS quota with a Windows job-object hard CPU cap across all 32 cores (threads still see every core, like a container). It is an approximation; confirm with real `docker run --cpus=0.1`.

### Step 0: where the time goes (before any change; one 190-char hero-style query, 27 chunks, b2b corpus)

| Host | model load | embed 1 query | vector search | BM25 | retrieve() | retrieve(decompose) | embed all 27 chunks (cold boot) |
|---|---:|---:|---:|---:|---:|---:|---:|
| full cores | 373 ms | 5.2 ms | 0.0 ms | 0.3 ms | 5.3 ms | 13.1 ms | 141 ms |
| emulated 0.1 vCPU, default threads | 10.6 s | 1,180 ms | 0.0 ms | 0.3 ms | 1,181 ms | 3,570 ms (p95 7.1 s) | 33.8 s |
| emulated 0.1 vCPU, threads=1 | 13.1 s | 1,182 ms | 0.0 ms | 0.4 ms | 882 ms | 4,151 ms (p95 7.1 s) | 43.3 s |

Finding: vector search and BM25 are negligible (<1 ms). Retrieval time is entirely query embedding (one ONNX forward pass per text), which is x3-4 for decomposed queries, and on a throttled CPU the cold-boot costs (model load, embedding the corpus) are tens of seconds. That reproduces the reported multi-second retrieval; thread count alone did not fix it in this emulation.

### After (FastEmbedder threads=1 + OMP/OPENBLAS=1, prebuilt index, per-text vector LRU + hits LRU pre-populated for every preset query, paraphrase, sanitized variant and decomposed sub-query; 4 domains)

| Host | model load | build_domains (prebuilt index) | warm-up | time to ready | preset/paraphrase p95 | custom (unseen) query p95, decomposed |
|---|---:|---:|---:|---:|---:|---:|
| full cores | 333 ms | 12 ms | 1.1 s | 1.5 s | < 0.1 ms | 63 ms |
| emulated 1 vCPU | 337 ms | 11 ms | 1.2 s | 1.6 s | < 0.1 ms | 66 ms |
| emulated 0.1 vCPU | 3.6 s | 17 ms | 13.0 s | 16.6 s | < 0.1 ms | 614 ms |

- Presets and paraphrases meet the < 50 ms p95 target on every host (cache hit, sub-millisecond), but only after startup warm-up (about 16 s of one-time cost at 0.1 vCPU, which is why `/api/health` reports `ready`).
- Custom (never-seen) queries are NOT < 50 ms: ~63 ms p95 on full cores (decomposed queries embed up to 9 texts) and ~0.6 s at an emulated 0.1 vCPU. Honest target for 0.1 vCPU is "< 1 s", met in the emulation.
- Cold boot at 0.1 vCPU no longer embeds the corpus (was 34-43 s) because `python -m app.rag.prebuild` bakes the per-domain `.npy` indexes at `docker build`.

### Hero retrieval recall (real bge-small, engineered path, decompose=True)
All four hero prompts and paraphrases retrieve every required fact chunk at k=4 (recall 1.00). At k=2 (8B path) hero recall is lower (travel 0.25, tenancy 0.60, b2b 0.67; nutrition 1.00), but every Tier-1 router prompt retrieves its fact chunk at k=2 (tests: `tests/test_domains.py`).
