"use client";

import { useState } from "react";
import type { Preset, PresetId } from "@/lib/types";

const ICONS: Record<PresetId, string> = {
  hallucination_trap: "🪤",
  semantic_cache: "⚡",
  tier1_triage: "🎫",
  prompt_injection: "🛡",
};

export function ControlBar({
  presets,
  activePreset,
  busy,
  followUpReady,
  drawerOpen,
  onPreset,
  onFollowUp,
  onCustom,
  onCacheTest,
  onToggleDrawer,
}: {
  presets: Preset[];
  activePreset: PresetId | null;
  busy: boolean;
  followUpReady: boolean;
  drawerOpen: boolean;
  onPreset: (p: Preset) => void;
  onFollowUp: () => void;
  onCustom: (q: string) => void;
  onCacheTest: () => void;
  onToggleDrawer: () => void;
}) {
  const [query, setQuery] = useState("");
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (q && !busy) onCustom(q);
  };

  return (
    <div className="space-y-3">
      <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4" role="group" aria-label="Challenge presets">
        {presets.map((p) => {
          const active = activePreset === p.id;
          return (
            <div
              key={p.id}
              className={`flex flex-col rounded-xl border bg-panel transition-colors ${
                active ? "border-eng/70 shadow-[0_0_0_1px_rgb(var(--eng)/0.3)]" : "border-line hover:border-mute/50"
              }`}
            >
              <button
                onClick={() => onPreset(p)}
                disabled={busy}
                aria-label={`Run challenge: ${p.title} (${p.tagline})`}
                className="flex flex-1 flex-col items-start gap-0.5 rounded-xl px-3.5 py-3 text-left disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span className="text-lg leading-none" aria-hidden>
                  {ICONS[p.id]}
                </span>
                <span className="mt-1 text-[13px] font-semibold leading-tight">{p.title}</span>
                <span className="text-[11px] text-mute">{p.tagline}</span>
              </button>
              {p.id === "semantic_cache" && (
                <button
                  onClick={onFollowUp}
                  disabled={busy || !followUpReady}
                  title={followUpReady ? "Fire a paraphrase of the first query" : "Run the challenge first"}
                  className="mx-3 mb-3 rounded-lg border border-eng/40 bg-eng/10 px-2.5 py-1.5 text-xs text-eng transition-colors hover:bg-eng/20 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  ↻ Run paraphrased follow-up
                </button>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <form onSubmit={submit} className="flex min-w-0 flex-1 gap-2">
          <label htmlFor="custom-query" className="sr-only">
            Custom query
          </label>
          <input
            id="custom-query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            maxLength={2000}
            placeholder="…or ask your own question about the vendor SLAs, SOPs and policies"
            className="min-w-0 flex-1 rounded-lg border border-line bg-panel px-3 py-2 text-sm outline-none placeholder:text-mute/70 focus:border-eng/70"
          />
          <button
            type="submit"
            disabled={busy || !query.trim()}
            className="rounded-lg bg-eng px-4 py-2 text-sm font-semibold text-bg transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
          >
            Race
          </button>
        </form>
        <div className="flex gap-2">
          <button
            onClick={onCacheTest}
            disabled={busy}
            className="flex-1 whitespace-nowrap rounded-lg border border-line bg-panel px-3 py-2 text-sm hover:border-eng/60 disabled:cursor-not-allowed disabled:opacity-50 sm:flex-none"
          >
            ⚡ Trigger Semantic Cache Test
          </button>
          <button
            onClick={onToggleDrawer}
            aria-expanded={drawerOpen}
            aria-controls="kb-drawer"
            className="flex-1 whitespace-nowrap rounded-lg border border-line bg-panel px-3 py-2 text-sm hover:border-eng/60 sm:flex-none"
          >
            📚 Knowledge Base
          </button>
        </div>
      </div>
    </div>
  );
}
