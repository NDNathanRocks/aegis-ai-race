import type { EngineeredRun, NaiveRun } from "./reducer";
import type { ModelMode, VerdictData } from "./types";

type AnyRun = NaiveRun | EngineeredRun;

export const MODEL_LABEL: Record<ModelMode, string> = {
  "70b": "Llama 3.3 70B Versatile",
  "8b": "Llama 3.1 8B Instant",
  auto: "Auto Tiered Routing",
};

/** Tokens sent to the model on the first attempt (what the parity meter shows), or null before the payload arrives. */
export function sentTokens(run: AnyRun): number | null {
  const first = run.payloads[0];
  return first ? first.token_count : null;
}

export function totalTokens(run: AnyRun): number {
  return run.promptTokens + run.completionTokens;
}

/** Positive numbers mean the engineered side saved that much. */
export interface Deltas {
  tokens: number;
  ms: number | null;
  usd: number;
}

export function compareRuns(naive: AnyRun, eng: AnyRun): Deltas {
  return {
    tokens: totalTokens(naive) - totalTokens(eng),
    ms: naive.totalMs !== null && eng.totalMs !== null ? naive.totalMs - eng.totalMs : null,
    usd: naive.costUsd - eng.costUsd,
  };
}

/** Measured (never hardcoded) input-token ratio, or null until both payloads are known. */
export function inputRatio(naive: AnyRun, eng: AnyRun): number | null {
  const a = sentTokens(naive);
  const b = sentTokens(eng);
  return a !== null && b !== null && b > 0 ? a / b : null;
}

export function correctAnswerSummary(v: VerdictData | null): string | null {
  if (!v || !v.key_applies || v.required.length === 0) return null;
  // Answer keys may list accepted spellings as `a|b`; show the first one.
  return v.required.map((r) => `${r.label} ${r.expected.split("|")[0]}`).join(" · ");
}

export function missingLabels(v: VerdictData): string[] {
  return v.required.filter((r) => !r.found).map((r) => r.label);
}
