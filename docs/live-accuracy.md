# Live accuracy (Groq, 2026-10-26)

Reproduce with `python scripts/live_accuracy.py` against a backend that has `GROQ_API_KEY` set. Each run is the domain's
hallucination-trap preset, with a fresh session so the semantic cache never answers. The score is the server's own
`verdict` event: the deterministic answer key in `backend/app/domains/`. Raw per-run logs, including the validated cards
where captured, are in [`live-accuracy/`](live-accuracy/).

Setup: `openai/gpt-oss-120b` (large tier) and `openai/gpt-oss-20b` (small tier), the deployed models, on a free-tier Groq
key (8,000 tokens per minute per model). The backend ran locally with `GROQ_RETRY_BUDGET_S=60` so calls waited for quota
instead of falling back, and with the per-visitor live limit raised. No run fell back to the simulator.

| Knowledge base | Side | Correct | 95% CI (Wilson) | Median cost | Median time |
|---|---|---:|---:|---:|---:|
| Enterprise B2B SLA (invoice audit) | naive (whole KB in the prompt) | 3/10 | 0.11–0.60 | $0.0572 | 2.4 s |
| Enterprise B2B SLA (invoice audit) | engineered | **9/10** | 0.60–0.98 | $0.0358 | 2.5 s |
| Air Canada & APPR | engineered | 5/5 | 0.57–1.00 | $0.0290 | |
| BC Tenancy + CRA | engineered | 5/5 | 0.57–1.00 | $0.0309 | |
| Restaurant Nutrition | engineered | 5/5 | 0.57–1.00 | $0.0412 | |

Costs use the app's flat enterprise price model ($15 per million tokens) on provider-reported token counts.

## What changed to get here

Before this run, the engineered side answered the B2B trap correctly in 1 of 4 live runs (two on 2026-10-25, two on
2026-10-26), always missing "Approved payout $36,000". The cause was the schema, not the model. `InvoiceAuditCard` had
fields for line-item findings and the total discrepancy, but none for the payout. The answer key only found 36,000 when the
model happened to fold the credit into a net line item, which the demo simulator always did and live models usually did
not. The card now has `billed_total_usd` and `approved_payout_usd`, with a validator requiring payout = billed total −
discrepancy, so the figure is structured and checked rather than left to chance.

## Caveats

- Small samples: the intervals are wide. The naive and engineered B2B batches ran back to back on the same day, not as
  paired races.
- The one engineered miss (B2B run 5) omitted both required figures after a critic retry. Its card was not captured
  (card logging was added after that batch started), so the cause is unknown.
- With a strong model and the whole knowledge base in its prompt, the naive side sometimes gets the answer right (3/10 here,
  and it was right on travel and nutrition in two live spot checks). The gap is largest on the multi-step invoice audit.
- Until 2026-10-26 the deployed backend used Llama 3.x model ids, which current Groq keys reject (404 `model_not_found`),
  so live visitors were silently served the simulator. The defaults are now the gpt-oss models measured here.
