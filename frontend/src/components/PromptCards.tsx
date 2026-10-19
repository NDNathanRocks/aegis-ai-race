"use client";

import { KIND_LABEL, orderedPresets } from "@/lib/domains";
import type { DomainInfo, DomainPreset, PresetId } from "@/lib/types";
import { Badge } from "./ui";

export const MAX_QUERY = 2000;

/** Three verbatim prompt cards for the active domain. Selecting one loads it into the editor. */
export function PromptCards({
  domain,
  selected,
  busy,
  onSelect,
  onRun,
}: {
  domain: DomainInfo;
  selected: PresetId | null;
  busy: boolean;
  onSelect: (p: DomainPreset) => void;
  onRun: () => void;
}) {
  return (
    <div className="grid gap-3 md:grid-cols-3" role="group" aria-label={`${domain.title} prompts`}>
      {orderedPresets(domain).map((p) => {
        const on = selected === p.id;
        return (
          <div
            key={p.id}
            data-testid="prompt-card"
            className={`flex min-w-0 flex-col rounded-lg border bg-panel transition-colors duration-150 ${on ? "border-eng" : "border-line hover:border-line-strong"}`}
          >
            <button
              type="button"
              onClick={() => onSelect(p)}
              aria-pressed={on}
              className="flex min-h-[44px] flex-1 flex-col items-start gap-1.5 rounded-lg px-3.5 py-3 text-left"
            >
              <Badge tone={p.kind === "hallucination_trap" ? "naive" : p.kind === "prompt_injection" ? "warn" : "eng"}>
                {KIND_LABEL[p.kind]}
              </Badge>
              <span className="text-[13px] font-semibold leading-tight">{p.title}</span>
              <span className="text-[11px] text-mute">{p.tagline}</span>
              <span className="mt-1 w-full whitespace-pre-wrap break-words text-xs leading-relaxed text-mute">{p.query}</span>
            </button>
            {on && (
              <button
                type="button"
                onClick={onRun}
                disabled={busy}
                className="m-3 mt-0 min-h-[44px] rounded-lg bg-eng px-4 text-sm font-semibold text-bg transition-opacity duration-150 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Run Race ▸
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function PromptEditor({
  domain,
  value,
  busy,
  cacheReady,
  followUpReady,
  kbOpen,
  onChange,
  onRun,
  onCacheTest,
  onFollowUp,
  onToggleKb,
}: {
  domain: DomainInfo;
  value: string;
  busy: boolean;
  cacheReady: boolean;
  followUpReady: boolean;
  kbOpen: boolean;
  onChange: (v: string) => void;
  onRun: () => void;
  onCacheTest: () => void;
  onFollowUp: () => void;
  onToggleKb: () => void;
}) {
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (value.trim() && !busy) onRun();
  };
  const btn =
    "min-h-[44px] rounded-lg border border-line bg-panel px-3 text-[13px] transition-colors duration-150 hover:border-line-strong disabled:cursor-not-allowed disabled:opacity-40";
  return (
    <form onSubmit={submit} className="space-y-2">
      <label htmlFor="query" className="sr-only">
        Your prompt
      </label>
      <textarea
        id="query"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        maxLength={MAX_QUERY}
        rows={4}
        placeholder={`Pick a card above or ask your own question about ${domain.title}…`}
        className="w-full resize-y rounded-lg border border-line bg-panel px-3 py-2.5 text-sm leading-relaxed outline-none placeholder:text-faint focus:border-eng"
      />
      <div className="flex flex-wrap items-center gap-2">
        <span className="num order-last w-full text-[11px] text-faint sm:order-none sm:w-auto sm:flex-1" aria-live="polite">
          {value.length} / {MAX_QUERY}
        </span>
        <button
          type="submit"
          disabled={busy || !value.trim()}
          className="min-h-[44px] flex-1 rounded-lg bg-eng px-5 text-sm font-semibold text-bg transition-opacity duration-150 disabled:cursor-not-allowed disabled:opacity-40 sm:flex-none"
        >
          Run Race ▸
        </button>
        <button
          type="button"
          onClick={onCacheTest}
          disabled={busy || !cacheReady}
          className={btn}
          title={cacheReady ? "Run the hero prompt, then its paraphrase" : "This domain has no paraphrase"}
        >
          ⚡ Trigger Semantic Cache Test
        </button>
        {followUpReady && (
          <button type="button" onClick={onFollowUp} disabled={busy} className={btn}>
            ↻ Run paraphrased follow-up
          </button>
        )}
        <button type="button" onClick={onToggleKb} aria-expanded={kbOpen} aria-controls="kb-drawer" className={btn}>
          📚 Knowledge Base
        </button>
      </div>
    </form>
  );
}
