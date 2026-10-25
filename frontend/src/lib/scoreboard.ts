import type { EngineeredRun, NaiveRun } from "./reducer";

/** Per-side totals over the races where both sides were checked against the answer key. */
export interface SideTally {
  spendUsd: number;
  correct: number;
  wrongSpendUsd: number;
}

export interface Scoreboard {
  races: number;
  latencySavedMs: number;
  costSavedUsd: number;
  hallucinationsPrevented: number;
  /** Races that had a verdict on both sides: the denominator for the cost-per-correct-answer figures. */
  judged: number;
  naive: SideTally;
  eng: SideTally;
}

const emptyTally = (): SideTally => ({ spendUsd: 0, correct: 0, wrongSpendUsd: 0 });

export const emptyScoreboard = (): Scoreboard => ({
  races: 0,
  latencySavedMs: 0,
  costSavedUsd: 0,
  hallucinationsPrevented: 0,
  judged: 0,
  naive: emptyTally(),
  eng: emptyTally(),
});

function tally(t: SideTally, run: NaiveRun | EngineeredRun): SideTally {
  const correct = run.verdict?.correct === true;
  return {
    spendUsd: t.spendUsd + run.costUsd,
    correct: t.correct + (correct ? 1 : 0),
    wrongSpendUsd: t.wrongSpendUsd + (correct ? 0 : run.costUsd),
  };
}

/**
 * Fold one finished pair of runs into the cumulative scoreboard. Savings can be negative: for example the
 * hallucination trap spends more tokens on the engineered side (retrieval + a critic retry) to get a correct answer,
 * which is why the board also tracks cost per correct answer.
 */
export function addRace(board: Scoreboard, naive: NaiveRun, eng: EngineeredRun): Scoreboard {
  // Degraded races (Groq failed, both sides fell back to the simulator) are not apples-to-apples: never counted.
  if (naive.degraded || eng.degraded) return board;
  if (naive.status !== "done" || eng.status !== "done" || naive.totalMs === null || eng.totalMs === null) {
    return board;
  }
  const judged = naive.verdict !== null && eng.verdict !== null;
  return {
    races: board.races + 1,
    latencySavedMs: board.latencySavedMs + (naive.totalMs - eng.totalMs),
    costSavedUsd: board.costSavedUsd + (naive.costUsd - eng.costUsd),
    hallucinationsPrevented: board.hallucinationsPrevented + (eng.hallucinationPrevented ? 1 : 0),
    judged: board.judged + (judged ? 1 : 0),
    naive: judged ? tally(board.naive, naive) : board.naive,
    eng: judged ? tally(board.eng, eng) : board.eng,
  };
}

/** Spend divided by correct answers; null when the side has no correct answer yet (cost per correct is unbounded). */
export function costPerCorrect(t: SideTally): number | null {
  return t.correct > 0 ? t.spendUsd / t.correct : null;
}

export function parseScoreboard(raw: string | null): Scoreboard {
  if (!raw) return emptyScoreboard();
  try {
    const v: unknown = JSON.parse(raw);
    if (typeof v !== "object" || v === null) return emptyScoreboard();
    const o = v as Record<string, unknown>;
    const numIn = (src: Record<string, unknown>, k: string): number =>
      typeof src[k] === "number" && Number.isFinite(src[k]) ? (src[k] as number) : 0;
    const num = (k: string) => numIn(o, k);
    const side = (k: string): SideTally => {
      const s = o[k];
      if (typeof s !== "object" || s === null) return emptyTally();
      const r = s as Record<string, unknown>;
      return { spendUsd: numIn(r, "spendUsd"), correct: numIn(r, "correct"), wrongSpendUsd: numIn(r, "wrongSpendUsd") };
    };
    return {
      races: num("races"),
      latencySavedMs: num("latencySavedMs"),
      costSavedUsd: num("costSavedUsd"),
      hallucinationsPrevented: num("hallucinationsPrevented"),
      judged: num("judged"),
      naive: side("naive"),
      eng: side("eng"),
    };
  } catch {
    return emptyScoreboard();
  }
}
