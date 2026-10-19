"use client";

import { forwardRef } from "react";
import type { ContextMode, ModelMode } from "@/lib/types";
import { SectionLabel, Segmented } from "./ui";

export const CONTEXT_OPTIONS: { id: ContextMode; label: string }[] = [
  { id: "full_kb", label: "Full KB Context Stuffing" },
  { id: "none", label: "No Knowledge Base / Raw LLM" },
];

export const MODEL_OPTIONS: { id: ModelMode; label: string }[] = [
  { id: "70b", label: "Llama 3.3 70B Versatile" },
  { id: "8b", label: "Llama 3.1 8B Instant" },
  { id: "auto", label: "Auto Tiered Routing (70B Naive vs 8B/70B Smart Router)" },
];

/** Race configuration. The section is focusable so the B2B nudge can scroll to and focus it. */
export const RaceConfigBar = forwardRef<
  HTMLElement,
  {
    contextMode: ContextMode;
    modelMode: ModelMode;
    disabled: boolean;
    onContext: (m: ContextMode) => void;
    onModel: (m: ModelMode) => void;
  }
>(function RaceConfigBar({ contextMode, modelMode, disabled, onContext, onModel }, ref) {
  return (
    <section
      ref={ref}
      id="race-config"
      tabIndex={-1}
      aria-label="Race configuration"
      className="grid scroll-mt-4 gap-3 rounded-lg border border-line bg-panel p-3 outline-none focus-visible:border-eng md:grid-cols-2"
    >
      <div>
        <SectionLabel>Naive side: context mode</SectionLabel>
        <Segmented label="Naive context mode" value={contextMode} options={CONTEXT_OPTIONS} onChange={onContext} disabled={disabled} />
      </div>
      <div>
        <SectionLabel>Model</SectionLabel>
        <label htmlFor="model-mode" className="sr-only">
          Model
        </label>
        <select
          id="model-mode"
          value={modelMode}
          disabled={disabled}
          onChange={(e) => onModel(e.target.value as ModelMode)}
          className="min-h-[44px] w-full rounded-lg border border-line bg-panel px-3 text-[13px] text-ink outline-none focus:border-eng disabled:cursor-not-allowed disabled:opacity-50"
        >
          {MODEL_OPTIONS.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
    </section>
  );
});
