"use client";

import { useState } from "react";
import { fmtTokens } from "@/lib/format";
import type { PayloadData, Side } from "@/lib/types";

export function InspectButton({
  side,
  available,
  open,
  onClick,
}: {
  side: Side;
  available: boolean;
  open: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!available}
      aria-expanded={open}
      aria-controls="payload-drawer"
      data-testid={`inspect-${side}`}
      className="min-h-[44px] w-full rounded-lg border border-line bg-panel px-3 text-[13px] text-mute transition-colors duration-150 hover:border-line-strong hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
    >
      Inspect Prompt &amp; Context Tokens
    </button>
  );
}

const SHADES = ["opacity-100", "opacity-70", "opacity-45", "opacity-25"];

function TokenStack({ payload, side }: { payload: PayloadData; side: Side }) {
  const total = payload.composition.reduce((a, c) => a + c.tokens, 0) || 1;
  const color = side === "naive" ? "bg-naive" : "bg-eng";
  return (
    <div>
      <div className="flex h-2 gap-px overflow-hidden rounded-sm border border-line bg-bg" role="img" aria-label="Token composition">
        {payload.composition.map((c, i) => (
          <div key={c.label} className={`${color} ${SHADES[i % SHADES.length]}`} style={{ width: `${(c.tokens / total) * 100}%` }} title={`${c.label}: ${c.tokens}`} />
        ))}
      </div>
      <ul className="mt-2 space-y-1">
        {payload.composition.map((c, i) => (
          <li key={c.label} className="flex items-center gap-2 text-[11px]">
            <span aria-hidden className={`inline-block h-2 w-2 rounded-sm ${color} ${SHADES[i % SHADES.length]}`} />
            <span className="flex-1 text-mute">{c.label}</span>
            <span className="num text-ink">{fmtTokens(c.tokens, payload.token_source)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Column({ side, payloads }: { side: Side; payloads: PayloadData[] }) {
  const [attempt, setAttempt] = useState(0);
  const p = payloads[Math.min(attempt, payloads.length - 1)];
  const tone = side === "naive" ? "text-naive" : "text-eng";
  if (!p) {
    return (
      <div className="rounded-lg border border-line bg-bg/40 p-3 text-xs text-mute">
        <h3 className={`mb-1 text-[13px] font-semibold ${tone}`}>{side === "naive" ? "Naive" : "Engineered"}</h3>
        No payload yet. Run a race first.
      </div>
    );
  }
  return (
    <div className="min-w-0 space-y-3 rounded-lg border border-line bg-bg/40 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className={`text-[13px] font-semibold ${tone}`}>{side === "naive" ? "Naive" : "Engineered"}</h3>
        <span className="num text-[11px] text-mute">
          {p.model} · {fmtTokens(p.token_count, p.token_source)} tokens
        </span>
      </div>
      {payloads.length > 1 && (
        <div role="tablist" aria-label={`${side} attempts`} className="flex gap-1">
          {payloads.map((x, i) => (
            <button
              key={x.attempt}
              role="tab"
              aria-selected={i === attempt}
              onClick={() => setAttempt(i)}
              className={`min-h-[44px] rounded border px-3 text-xs ${i === attempt ? "border-line-strong bg-raised text-ink" : "border-line text-mute"}`}
            >
              Attempt {x.attempt}
            </button>
          ))}
        </div>
      )}
      <TokenStack payload={p} side={side} />
      <ol className="space-y-2">
        {p.messages.map((m, i) => (
          <li key={i}>
            <div className="mb-1 text-[10px] uppercase tracking-wider text-mute">{m.role}</div>
            {/* Plain text child: React escapes it, never dangerouslySetInnerHTML. */}
            <pre className="scroll-thin max-h-56 overflow-auto whitespace-pre-wrap break-words rounded border border-line bg-bg/60 p-2 font-mono text-[11px] leading-relaxed text-ink">
              {m.content}
            </pre>
          </li>
        ))}
      </ol>
      {p.chunks && p.chunks.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wider text-mute">Retrieved chunks</div>
          <ul className="space-y-1">
            {p.chunks.map((c) => (
              <li key={c.chunk_id} className="flex items-center justify-between gap-2 text-[11px]">
                <span className="min-w-0 truncate">
                  <span className="num text-mute">#{c.rank}</span> {c.doc_title} <span className="text-mute">§ {c.section}</span>
                </span>
                <span className="num text-mute">RRF {c.rrf_score.toFixed(4)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Inline (in-flow, so iframe resize tracks it) two-column compare of the exact context sent to each model. */
export function PayloadDrawer({
  open,
  naive,
  engineered,
  onClose,
}: {
  open: boolean;
  naive: PayloadData[];
  engineered: PayloadData[];
  onClose: () => void;
}) {
  return (
    <div
      id="payload-drawer"
      className={`grid transition-[grid-template-rows] duration-150 ${open ? "mt-4 grid-rows-[1fr]" : "grid-rows-[0fr]"}`}
      aria-hidden={!open}
      inert={!open}
    >
      <div className="min-h-0 overflow-hidden">
        <section aria-label="Prompt and context payloads" className="rounded-lg border border-line bg-panel p-3">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold">Prompt &amp; Context Tokens</h2>
              <p className="text-[11px] text-mute">Exactly what each side sent to the model. The API key is never part of a payload.</p>
            </div>
            <button type="button" onClick={onClose} className="min-h-[44px] rounded border border-line px-3 text-xs text-mute hover:text-ink">
              Close
            </button>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <Column side="naive" payloads={naive} />
            <Column side="engineered" payloads={engineered} />
          </div>
        </section>
      </div>
    </div>
  );
}
