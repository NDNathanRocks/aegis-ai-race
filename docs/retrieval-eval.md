# Retrieval ablation

Embeddings `BAAI/bge-small-en-v1.5`, BM25 (`rank_bm25`), RRF k = 60, 10 candidates per ranker. Reproduce: `python -m app.eval.retrieval`.
51 questions across 4 domains (24 lexical, 27 paraphrase).

### All questions (n = 51)

| Configuration | hit@1 | hit@2 | hit@4 | MRR@10 |
|---|---:|---:|---:|---:|
| BM25 only | 0.67 | 0.80 | 0.92 | 0.777 |
| Dense only | 0.67 | 0.84 | 0.96 | 0.794 |
| Hybrid (RRF) | 0.73 | 0.82 | 0.94 | 0.820 |
| Hybrid + sub-queries | 0.73 | 0.82 | 0.94 | 0.822 |

### Lexical questions (n = 24)

| Configuration | hit@1 | hit@2 | hit@4 | MRR@10 |
|---|---:|---:|---:|---:|
| BM25 only | 0.83 | 0.92 | 1.00 | 0.903 |
| Dense only | 0.75 | 0.92 | 1.00 | 0.854 |
| Hybrid (RRF) | 0.79 | 0.88 | 1.00 | 0.875 |
| Hybrid + sub-queries | 0.79 | 0.88 | 1.00 | 0.875 |

### Paraphrase questions (n = 27)

| Configuration | hit@1 | hit@2 | hit@4 | MRR@10 |
|---|---:|---:|---:|---:|
| BM25 only | 0.52 | 0.70 | 0.85 | 0.665 |
| Dense only | 0.59 | 0.78 | 0.93 | 0.740 |
| Hybrid (RRF) | 0.67 | 0.78 | 0.89 | 0.771 |
| Hybrid + sub-queries | 0.67 | 0.78 | 0.89 | 0.774 |

### Hybrid + sub-queries vs each single lens: MRR difference, paired bootstrap 95% CI

- vs BM25 only: +0.045 [-0.025, +0.119]
- vs Dense only: +0.028 [-0.025, +0.081]

### Misses at k = 4 for Hybrid + sub-queries (3)

- `travel_appr` (paraphrase): I booked yesterday and my trip is in two weeks. Can I back out without paying anything?
- `travel_appr` (paraphrase): What can I do if the airline turns down my request for money for the late flight?
- `nutrition` (paraphrase): Which loaf can someone who avoids milk safely pick?
