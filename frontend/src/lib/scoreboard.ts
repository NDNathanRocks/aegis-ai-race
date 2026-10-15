import type { EngineeredRun, NaiveRun } from "./reducer";

export interface Scoreboard {
  races: number;
  latencySavedMs: number;
  costSavedUsd: number;
  hallucinationsPrevented: number;
}

export const emptyScoreboard = (): Scoreboard => ({
  races: 0,
  latencySavedMs: 0,
  costSavedUsd: 0,
  hallucinationsPrevented: 0,
});

/**
 * Fold one finished pair of runs into the cumulative scoreboard. Savings can be negative: for example the
 * hallucination trap spends more tokens on the engineered side (retrieval + a critic retry) to get a correct answer.
 */
export function addRace(board: Scoreboard, naive: NaiveRun, eng: EngineeredRun): Scoreboard {
  if (naive.status !== "done" || eng.status !== "done" || naive.totalMs === null || eng.totalMs === null) {
    return board;
  }
  return {
    races: board.races + 1,
    latencySavedMs: board.latencySavedMs + (naive.totalMs - eng.totalMs),
    costSavedUsd: board.costSavedUsd + (naive.costUsd - eng.costUsd),
    hallucinationsPrevented: board.hallucinationsPrevented + (eng.hallucinationPrevented ? 1 : 0),
  };
}

export function parseScoreboard(raw: string | null): Scoreboard {
  if (!raw) return emptyScoreboard();
  try {
    const v: unknown = JSON.parse(raw);
    if (typeof v !== "object" || v === null) return emptyScoreboard();
    const o = v as Record<string, unknown>;
    const num = (k: string): number => (typeof o[k] === "number" && Number.isFinite(o[k]) ? (o[k] as number) : 0);
    return {
      races: num("races"),
      latencySavedMs: num("latencySavedMs"),
      costSavedUsd: num("costSavedUsd"),
      hallucinationsPrevented: num("hallucinationsPrevented"),
    };
  } catch {
    return emptyScoreboard();
  }
}
