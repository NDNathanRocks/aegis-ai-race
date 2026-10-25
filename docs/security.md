# Security notes (v2 audit)

Audited the v2 diff against the running backend (demo mode, no Groq key) and the test suite.

| Area | Status |
|---|---|
| **CORS** | Explicit origin allowlist from `CORS_ORIGINS`; a request from an unlisted origin gets no `Access-Control-Allow-Origin`. Methods `GET/POST/OPTIONS`, header `Content-Type` only. Set it to your Vercel origin in production. |
| **Rate limiting** | Per-client sliding window (30/min) plus a lower live-Groq budget (`RATE_LIMIT_LIVE_PER_MIN`, default 6; over budget the whole race runs simulated, never half live). **Fixed in this audit:** the Docker `CMD` ran uvicorn with `--proxy-headers --forwarded-allow-ips='*'`, so any client could spoof `X-Forwarded-For` and evade the limiter. It now runs `--no-proxy-headers`; the app honours the header only with `TRUST_PROXY=1` (right-most `TRUSTED_PROXY_HOPS` entries). Verified: 30 spoofed-IP requests pass, the rest get 429. Set `TRUST_PROXY=1` on Render. |
| **Input validation** | `domain`, `context_mode`, `model_mode` are enums; a client-supplied model string is ignored and never reaches Groq; unknown `preset_id` for the domain, malformed `race_id`/`session_id`, and queries over 2000 chars return 422. |
| **Prompt injection** | The engineered path sanitizes input (`guardrails.scan`) and treats user text as data. The naive path is intentionally unguarded (that is the demo) but is length-capped, has no tools and no secrets in context. Knowledge bases are repo-controlled; there is no upload path, so no stored-injection route. |
| **Secret exposure** | `GROQ_API_KEY` appears only in the outbound `Authorization` header. `/api/config`, SSE events (including `payload`), errors and logs never contain it; a test scans SSE output, config and logs for the key value. |
| **Output rendering** | Payload inspector and model output are rendered as React text, never `dangerouslySetInnerHTML`. |
| **Known limits** | In-memory limiter and cache are per process (single worker; use Redis to scale). A race side that finished live before its sibling degraded keeps its real output; the race is flagged and excluded from the scoreboard. |

## Phase 3 hardening (2026-10-24)

| Area | Change |
|---|---|
| **Prompt injection** | Not provably impossible: a pattern filter cannot catch every paraphrase. `guardrails.scan` now normalises input (NFKC, zero-width stripped, leetspeak folded) and also matches a letters-only form, and adds `new_instructions` and `delimiter_spoof` patterns (`</context>`, `SYSTEM:` and similar). Backing layers: user text is framed as untrusted data, the model has no tools and no secrets in context, output must validate against a strict Pydantic schema, and the critic checks grounding. The naive path is intentionally unguarded. |
| **Headers** | Frontend: CSP, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, `Permissions-Policy`. Backend: `nosniff`, `Referrer-Policy: no-referrer`, `default-src 'none'`. HSTS is left to the host (Vercel / HF). |
| **Rate limits** | `/api/cache/reset` and `/api/kb/*`, `/api/domains` share a 120/min per-client limiter (`RATE_LIMIT_META_PER_MIN`). |
| **SQL** | pgvector table names go through `psycopg.sql.Identifier` (they were already regex-validated). |
| **Errors** | SSE `internal_error` carries a generic message; details are logged server-side. |
| **Repo hygiene** | Full git history scanned for key patterns and secret-like files: none found. `.env.*` and `.playwright-mcp/` are gitignored. Containers run as non-root; the compose Redis/Postgres publish no host ports. |

## Dependency audit (2026-10-25)
- **npm:** `npm audit --omit=dev` flagged `postcss` bundled inside Next 15.5.28 (the latest 15.x). `package.json` now has `overrides: { postcss: ^8.5.30 }`; audit reports 0 vulnerabilities, and tsc, vitest and `next build` pass.
- **Python:** `pip-audit` found 44 advisories in three transitive packages (pillow via fastembed, filelock, certifi). Floors added to `pyproject.toml` (`pillow>=13.0.0`, `filelock>=4.2.1`, `certifi>=2026.10.19`); re-audit is clean and all 282 tests pass.
- **CI:** both audits now run on every push (`npm audit --audit-level=high`, `pip-audit`).
