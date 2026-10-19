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
