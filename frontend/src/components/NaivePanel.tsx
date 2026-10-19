"use client";

import { useMemo } from "react";
import { inlineBold, segmentize } from "@/lib/highlight";
import { fmtMs, fmtTokens, fmtUsd } from "@/lib/format";
import type { NaiveRun } from "@/lib/reducer";
import { Badge, SectionLabel, Stat, StatusHint } from "./ui";
import { InspectButton } from "./PayloadDrawer";
import { ModeBadge } from "./ModeBadge";

function Inline({ text }: { text: string }) {
  return (
    <>
      {inlineBold(text).map((p, i) =>
        p.bold ? (
          <strong key={i} className="font-semibold text-ink">
            {p.text}
          </strong>
        ) : (
          <span key={i}>{p.text.replace(/\*\*/g, "")}</span>
        ),
      )}
    </>
  );
}

function Stage({ label, sub, active, done }: { label: string; sub: string; active: boolean; done: boolean }) {
  return (
    <div
      className={`flex-1 rounded-lg border px-2.5 py-2 text-center transition-colors ${
        active ? "border-naive bg-naive/10" : done ? "border-line bg-raised" : "border-line bg-panel opacity-60"
      }`}
    >
      <div className="text-xs font-medium">{label}</div>
      <div className="font-mono text-[10px] text-mute">{sub}</div>
    </div>
  );
}

export function NaivePanel({
  run,
  elapsedMs,
  inspectOpen,
  onInspect,
}: {
  run: NaiveRun;
  elapsedMs: number | null;
  inspectOpen: boolean;
  onInspect: () => void;
}) {
  const claims = useMemo(() => run.analysis?.ungrounded_claims ?? [], [run.analysis]);
  const segments = useMemo(() => segmentize(run.text, claims), [run.text, claims]);
  const running = run.status === "running";
  const streaming = running && run.text.length > 0;

  return (
    <section
      aria-label="Naive LLM wrapper"
      className="flex min-w-0 flex-col rounded-2xl border border-naive/30 bg-panel"
    >
      <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-naive">Naive LLM Wrapper</h2>
          <p className="text-[11px] text-mute">One prompt, one big model, no safety net</p>
        </div>
        <ModeBadge mode={run.mode} reason={run.fallbackReason} provider={run.provider} model={run.model} />
      </header>
      <StatusHint hint={run.statusHint} />

      <div className="space-y-4 p-4">
        <div className="flex items-center gap-1.5" aria-label="Pipeline">
          <Stage label="Raw Prompt" sub={run.contextMode === "none" ? "no context" : "full KB stuffed"} active={false} done={run.status !== "idle"} />
          <span aria-hidden className="text-mute">→</span>
          <Stage label="Heavy 70B LLM" sub={run.model ?? "llama-3.3-70b"} active={running && !streaming} done={streaming || run.status === "done"} />
          <span aria-hidden className="text-mute">→</span>
          <Stage label="Unstructured Text" sub="free-form" active={streaming} done={run.status === "done"} />
        </div>

        <div className="grid grid-cols-3 gap-3 rounded-lg border border-line bg-raised px-3 py-2.5">
          <Stat label="Elapsed" value={fmtMs(elapsedMs)} />
          <Stat label="Tokens" value={fmtTokens(run.promptTokens + run.completionTokens, run.tokenSource)} />
          <Stat label="Cost @ $15/1M" value={fmtUsd(run.costUsd)} />
        </div>

        <InspectButton side="naive" available={run.payloads.length > 0} open={inspectOpen} onClick={onInspect} />

        <div>
          <SectionLabel>Raw output</SectionLabel>
          <div
            aria-live="off"
            className={`scroll-thin min-h-[11rem] max-h-[26rem] overflow-y-auto whitespace-pre-wrap rounded-xl border border-line bg-bg/60 p-3 text-[13px] leading-relaxed ${
              streaming ? "caret" : ""
            }`}
          >
            {run.status === "idle" && <span className="text-mute">Pick a challenge to start the race.</span>}
            {running && !run.text && <span className="text-mute">Waiting for the model…</span>}
            {segments.map((s, i) =>
              s.reasons.length ? (
                <mark
                  key={i}
                  title={s.reasons.join(" · ")}
                  className="cursor-help rounded-sm bg-bad/20 text-ink underline decoration-bad decoration-wavy underline-offset-2"
                >
                  <Inline text={s.text} />
                </mark>
              ) : (
                <Inline key={i} text={s.text} />
              ),
            )}
          </div>
        </div>

        {run.analysis && (
          <div className="space-y-2" aria-label="Failure analysis">
            <div className="flex flex-wrap gap-1.5">
              <Badge tone={claims.length ? "bad" : "good"}>
                {claims.length ? `${claims.length} ungrounded claim${claims.length > 1 ? "s" : ""}` : "No ungrounded claims found"}
              </Badge>
              <Badge tone={run.analysis.schema_valid ? "good" : "bad"}>
                Schema {run.analysis.schema_valid ? "valid" : "invalid"}
              </Badge>
            </div>
            {claims.length > 0 && (
              <ul className="space-y-1 text-[11px] text-mute">
                {Array.from(new Set(claims.map((c) => c.reason))).map((r) => (
                  <li key={r} className="flex gap-1.5">
                    <span aria-hidden className="text-bad">✕</span>
                    {r}
                  </li>
                ))}
              </ul>
            )}
            {run.analysis.schema_errors.length > 0 && (
              <p className="text-[11px] text-mute">
                <span className="text-bad">✕</span> {run.analysis.schema_errors[0]}
              </p>
            )}
          </div>
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
