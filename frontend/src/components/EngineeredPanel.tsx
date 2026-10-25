"use client";

import { useState } from "react";
import { RETRIEVAL_NAME, RETRIEVAL_TECH, lensOf } from "@/lib/brand";
import { fmtMs, fmtTokens, fmtUsd } from "@/lib/format";
import type { EngineeredRun, NodeState, NodeStatus } from "@/lib/reducer";
import { ModeBadge } from "./ModeBadge";
import { PipelineNode } from "./PipelineNode";
import { ResultCard } from "./ResultCard";
import { Badge, MeterBar, SectionLabel, Stat, StatusHint } from "./ui";
import { InspectButton } from "./PayloadDrawer";

const TIER_THRESHOLD = 0.5;

function combinedGeneratorStage(run: EngineeredRun): { status: NodeStatus; latency: number | null } {
  const gen = run.nodes.generator;
  const val = run.nodes.validator;
  const latency = gen.latencyMs === null && val.latencyMs === null ? null : (gen.latencyMs ?? 0) + (val.latencyMs ?? 0);
  if (val.status === "done" || val.status === "error") return { status: val.status, latency };
  if (gen.status === "skipped") return { status: "skipped", latency };
  if (gen.status === "idle") return { status: "idle", latency };
  return { status: "active", latency };
}

function criticStage(run: EngineeredRun): { status: NodeStatus; latency: number | null } {
  const c = run.nodes.critic;
  const last = run.critic[run.critic.length - 1];
  const finished = run.nodes.validator.status === "done" || run.nodes.validator.status === "error";
  if (run.triad && finished) return { status: last && !last.passed ? "error" : "done", latency: c.latencyMs };
  return { status: c.status, latency: c.latencyMs };
}

function RouterBody({ run }: { run: EngineeredRun }) {
  const r = run.router;
  if (!r) return null;
  const pct = r.complexity_score * 100;
  return (
    <div className="space-y-3 text-xs">
      <div>
        <div className="mb-1 flex justify-between text-[11px]">
          <span className="text-mute">Complexity score</span>
          <span className="font-mono">{r.complexity_score.toFixed(2)}</span>
        </div>
        <div className="relative h-2 rounded-full bg-line/70">
          <div className="h-full rounded-full bg-eng" style={{ width: `${pct}%` }} />
          <span
            aria-hidden
            title="Tier threshold: at or above this, route to the heavy model"
            className="absolute top-[-3px] h-[14px] w-px bg-ink/70"
            style={{ left: `${TIER_THRESHOLD * 100}%` }}
          />
        </div>
        <div className="mt-1 flex justify-between font-mono text-[10px] text-mute">
          <span>simple → 8B</span>
          <span>complex → 70B</span>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Badge tone={r.tier === "8b" ? "good" : "warn"} title={r.model}>
          {r.tier === "8b" ? "⚡ 8B fast tier · 1/15 price" : "🧠 70B heavy tier"}
        </Badge>
        <Badge>task: {r.card_kind.replace("_", " ")}</Badge>
        {r.injection_detected ? (
          <Badge tone="warn">🛡 injection stripped</Badge>
        ) : (
          <Badge tone="good">guardrail: clean</Badge>
        )}
      </div>
      {r.injection_detected && (
        <div className="space-y-1.5 rounded-lg border border-warn/30 bg-warn/5 p-2">
          <div className="flex flex-wrap gap-1">
            {r.injection_patterns.map((p) => (
              <Badge key={p} tone="warn">
                {p}
              </Badge>
            ))}
          </div>
          <div className="text-[11px] text-mute">
            Sanitized query: <span className="font-mono text-ink">&ldquo;{r.sanitized_query}&rdquo;</span>
          </div>
        </div>
      )}
      <div className="font-mono text-[10px] text-mute">{r.reason}</div>
    </div>
  );
}

function CacheBody({ run }: { run: EngineeredRun }) {
  const c = run.cache;
  if (!c) return null;
  return (
    <div className="space-y-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={c.hit ? "good" : "neutral"} className="!text-xs">
          {c.hit ? "HIT" : "MISS"}
        </Badge>
        <span className="font-mono">
          similarity {c.similarity === null ? "n/a (empty cache)" : `${(c.similarity * 100).toFixed(1)}%`}
        </span>
        <span className="text-mute">threshold {(c.threshold * 100).toFixed(0)}%</span>
      </div>
      {c.hit && c.matched_query && (
        <p className="text-[11px] text-mute">
          Matched earlier query: <span className="text-ink">&ldquo;{c.matched_query}&rdquo;</span>. Retrieval, generation
          and critic skipped; $0.00 spent.
        </p>
      )}
    </div>
  );
}

function RetrieverBody({ run }: { run: EngineeredRun }) {
  if (!run.chunks.length) return null;
  const max = Math.max(...run.chunks.map((c) => c.rrf_score));
  const docs = new Set(run.chunks.map((c) => c.doc_id)).size;
  const both = run.chunks.filter((c) => lensOf(c.dense_score, c.bm25_score) === "both").length;
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-mute">
        {run.chunks.length} passages from {docs} {docs === 1 ? "document" : "documents"}, {both} confirmed by both lenses.
        Only these go to the model; the full knowledge base never does.
      </p>
      <ol className="space-y-1.5">
        {run.chunks.map((c) => (
          <li key={c.chunk_id}>
            <details className="group rounded-lg border border-line bg-bg/40">
              <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-1.5 text-xs">
                <span className="font-mono text-mute">#{c.rank}</span>
                <span className="min-w-0 flex-1 truncate">
                  {c.doc_title} <span className="text-mute">§ {c.section}</span>
                </span>
                <LensBadge lens={lensOf(c.dense_score, c.bm25_score)} />
                <span className="hidden font-mono text-[10px] text-mute sm:inline">
                  dense {c.dense_score === null ? "-" : c.dense_score.toFixed(2)} · bm25{" "}
                  {c.bm25_score === null ? "-" : c.bm25_score.toFixed(1)}
                </span>
                <Badge tone="eng" title="Reciprocal Rank Fusion score">
                  RRF {c.rrf_score.toFixed(4)}
                </Badge>
              </summary>
              <div className="border-t border-line px-2.5 pb-2 pt-1.5">
                <div className="mb-1.5 h-1 rounded-full bg-line/70">
                  <div className="h-full rounded-full bg-eng" style={{ width: `${(c.rrf_score / max) * 100}%` }} />
                </div>
                <p className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-mute">{c.text}</p>
              </div>
            </details>
          </li>
        ))}
      </ol>
    </div>
  );
}

const LENS_LABEL = { both: "both lenses", exact: "exact lens", meaning: "meaning lens" } as const;

function LensBadge({ lens }: { lens: keyof typeof LENS_LABEL }) {
  const title =
    lens === "both"
      ? "Ranked by keyword and semantic search: the strongest evidence"
      : lens === "exact"
        ? "Found by keyword search: exact terms or figures matched"
        : "Found by semantic search: same meaning, different wording";
  return (
    <Badge tone={lens === "both" ? "good" : "neutral"} title={title}>
      {LENS_LABEL[lens]}
    </Badge>
  );
}

function GeneratorBody({ run }: { run: EngineeredRun }) {
  const [tab, setTab] = useState<"card" | "json" | "stream">("card");
  const generating = run.nodes.generator.status === "active";
  const validation = run.validation;
  const tabs = [
    { id: "card", label: "Structured card" },
    { id: "json", label: "Validated JSON" },
    { id: "stream", label: "Raw stream" },
  ] as const;
  const active = !run.card && run.draft ? "stream" : tab;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        {run.generator && <Badge title="Model that produced the draft">{run.generator.model}</Badge>}
        {run.nodes.generator.runs > 1 && <Badge tone="warn">attempt {run.nodes.generator.runs}</Badge>}
        {validation && (
          <Badge tone={validation.valid ? "good" : "bad"}>
            {validation.valid ? "✓ Pydantic valid" : "✕ schema invalid"}
          </Badge>
        )}
      </div>

      <div role="tablist" aria-label="Output view" className="flex gap-1 border-b border-line">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={active === t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 min-h-[44px] px-3 text-xs transition-colors ${
              active === t.id ? "border-eng text-ink" : "border-transparent text-mute hover:text-ink"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="scroll-thin max-h-80 overflow-auto rounded-lg border border-line bg-bg/50 p-3">
        {active === "card" &&
          (run.card ? (
            <ResultCard card={run.card} chunks={run.chunks} />
          ) : (
            <p className="text-xs text-mute">{generating ? "Generating a draft…" : "Waiting for a validated card…"}</p>
          ))}
        {active === "json" &&
          (run.rawJson ? (
            <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed">{run.rawJson}</pre>
          ) : (
            <p className="text-xs text-mute">No validated JSON yet.</p>
          ))}
        {active === "stream" && (
          <pre
            className={`whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-mute ${generating ? "caret" : ""}`}
          >
            {run.draft || "(nothing generated: served from cache or not started)"}
          </pre>
        )}
      </div>
      {validation && !validation.valid && (
        <ul className="space-y-0.5 text-[11px] text-bad">
          {validation.errors.map((e) => (
            <li key={e}>✕ {e}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CriticBody({ run }: { run: EngineeredRun }) {
  const t = run.triad;
  return (
    <div className="space-y-3">
      {run.critic.length > 0 && (
        <ol className="space-y-1.5">
          {run.critic.map((c, i) => (
            <li key={i} className={`rounded-lg border px-2.5 py-1.5 text-xs ${c.passed ? "border-good/30 bg-good/5" : "border-bad/30 bg-bad/5"}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">
                  Attempt {i + 1}: {c.passed ? "✓ grounded" : "✕ rejected"}
                </span>
                <span className="font-mono text-[11px] text-mute">faithfulness {Math.round(c.faithfulness * 100)}%</span>
              </div>
              {c.flagged_claims.length > 0 && (
                <ul className="mt-1 space-y-0.5 text-[11px] text-mute">
                  {c.flagged_claims.map((f) => (
                    <li key={f}>↳ {f}</li>
                  ))}
                </ul>
              )}
              {c.retry_requested && <div className="mt-1 text-[11px] text-warn">↻ sent back to the generator with feedback</div>}
            </li>
          ))}
        </ol>
      )}
      <div>
        <SectionLabel>RAG Triad</SectionLabel>
        <div className="grid gap-2.5 sm:grid-cols-2">
          <MeterBar label="Faithfulness" value={t?.faithfulness ?? null} hint="Share of numeric and textual claims supported by the retrieved documents" />
          <MeterBar label="Context recall" value={t ? t.context_recall : null} hint="Share of the preset's ground-truth facts present in the retrieved context (presets only)" />
          <MeterBar label="Context relevance" value={t?.context_relevance ?? null} hint="How relevant the retrieved chunks are to the question" />
          <MeterBar label="Schema validity" value={t?.schema_validity ?? null} hint="Pydantic validation passed" />
        </div>
      </div>
    </div>
  );
}

export function EngineeredPanel({
  run,
  elapsedMs,
  inspectOpen,
  onInspect,
}: {
  run: EngineeredRun;
  elapsedMs: number | null;
  inspectOpen: boolean;
  onInspect: () => void;
}) {
  const n: Record<string, NodeState> = run.nodes;
  const gen = combinedGeneratorStage(run);
  const critic = criticStage(run);
  const cacheName = run.cache?.backend === "redis" ? "Redis Semantic Cache" : "Semantic Cache";
  const retried = run.critic.length > 1 || run.nodes.generator.runs > 1;

  return (
    <section aria-label="Engineered AI platform" className="flex min-w-0 flex-col rounded-2xl border border-eng/30 bg-panel">
      <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-eng">Engineered AI Platform</h2>
          <p className="text-[11px] text-mute" title={RETRIEVAL_TECH}>
            Router → Cache → DualSight → Generator → Critic → Validator
          </p>
        </div>
        <ModeBadge mode={run.mode} reason={run.fallbackReason} provider={run.provider} model={run.model} />
      </header>
      <StatusHint hint={run.statusHint} />

      <div className="space-y-4 p-4">
        <div className="grid grid-cols-3 gap-3 rounded-lg border border-line bg-raised px-3 py-2.5">
          <Stat label="Elapsed" value={fmtMs(elapsedMs)} tone={run.cacheHit ? "good" : undefined} />
          <Stat label="Tokens" value={fmtTokens(run.promptTokens + run.completionTokens, run.tokenSource)} />
          <Stat label="Cost @ $15/1M" value={fmtUsd(run.costUsd)} tone={run.cacheHit ? "good" : undefined} />
        </div>

        <InspectButton side="engineered" available={run.payloads.length > 0} open={inspectOpen} onClick={onInspect} />

        <ol aria-label="Pipeline">
          <PipelineNode
            index={1}
            title="Guardrail & Semantic Router"
            subtitle="Injection scan · complexity score · model tier"
            status={n.router?.status ?? "idle"}
            latencyMs={n.router?.latencyMs ?? null}
            badges={run.router && <Badge tone={run.router.tier === "8b" ? "good" : "warn"}>{run.router.tier.toUpperCase()}</Badge>}
          >
            <RouterBody run={run} />
          </PipelineNode>
          <PipelineNode
            index={2}
            title={cacheName}
            subtitle="Cosine similarity ≥ 0.92 returns the stored answer"
            status={n.cache?.status ?? "idle"}
            latencyMs={n.cache?.latencyMs ?? null}
            badges={run.cache && <Badge tone={run.cache.hit ? "good" : "neutral"}>{run.cache.hit ? "HIT" : "MISS"}</Badge>}
          >
            <CacheBody run={run} />
          </PipelineNode>
          <PipelineNode
            index={3}
            title={RETRIEVAL_NAME}
            subtitle="Exact-match + meaning-match search over your documents, fused into one ranking"
            status={n.retriever?.status ?? "idle"}
            latencyMs={n.retriever?.latencyMs ?? null}
            badges={run.chunks.length > 0 && <Badge>{run.chunks.length} chunks</Badge>}
          >
            <RetrieverBody run={run} />
          </PipelineNode>
          <PipelineNode
            index={4}
            title="Generator + Pydantic Validator"
            subtitle="Grounded draft → strict schema validation"
            status={gen.status}
            latencyMs={gen.latency}
            badges={run.cacheHit && <Badge tone="good" title="The stored answer was reused">generator skipped · served from cache</Badge>}
          >
            <GeneratorBody run={run} />
          </PipelineNode>
          <PipelineNode
            index={5}
            title="Critic & Eval Harness"
            subtitle="Claim-level grounding check · faithfulness · recall"
            status={critic.status}
            latencyMs={critic.latency}
            badges={
              run.cacheHit ? (
                <Badge tone="good" title="Scores were stored with the cached answer">critic skipped · cached scores</Badge>
              ) : (
                retried && <Badge tone="warn">↻ self-corrected</Badge>
              )
            }
            last
          >
            <CriticBody run={run} />
          </PipelineNode>
        </ol>

        {run.hallucinationPrevented && run.status === "done" && (
          <p className="rounded-lg border border-good/40 bg-good/10 px-3 py-2 text-xs text-good">
            🛡 Hallucination prevented: the critic caught an ungrounded claim and forced a corrected answer.
          </p>
        )}
        {run.error && (
          <p role="alert" className="rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
            {run.error}
          </p>
        )}
      </div>
    </section>
  );
}
