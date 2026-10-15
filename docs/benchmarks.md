# Benchmark

Mode: **demo**, embeddings `BAAI/bge-small-en-v1.5`, cache `memory`, vector store `local`

| Challenge | Naive time | Engineered time | Naive cost | Engineered cost | Engineered tier | Notes |
|---|---:|---:|---:|---:|:--:|---|
| The Hallucination Trap | 3.93 s | 6.64 s | $0.0031 | $0.0334 | 70B | critic caught & corrected a hallucination |
| The Semantic Cache Race | 3.56 s | 0.46 s | $0.0017 | $0.0005 | 8B |  |
| Simple Tier-1 Triage | 3.81 s | 0.40 s | $0.0021 | $0.0006 | 8B |  |
| Adversarial Injection | 2.55 s | 0.48 s | $0.0016 | $0.0005 | 8B |  |

**Semantic cache** (20 runs): MISS median 470 ms; HIT median **7.3 ms**, p95 7.9 ms, cost $0.00; naive repeat 3.55 s.
