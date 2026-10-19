import { describe, expect, it } from "vitest";
import { inlineBold, segmentize } from "@/lib/highlight";
import { engineeredReducer, initialEngineered, initialNaive, naiveReducer, type EngineeredRun, type NaiveRun } from "@/lib/reducer";
import { addRace, emptyScoreboard, parseScoreboard } from "@/lib/scoreboard";
import { fmtMs, fmtUsd } from "@/lib/format";

const common = { run_id: "r", side: "naive" as const, t_ms: 1 };

function naiveDone(ms: number, cost: number): NaiveRun {
  return naiveReducer(initialNaive(), {
    type: "event",
    event: {
      event: "done",
      data: {
        ...common, total_ms: ms, cache_hit: false, hallucination_prevented: false, mode: "demo",
        usage: { prompt_tokens: 1, completion_tokens: 1, tier: "70b", cost_usd: cost, source: "estimate" },
      },
    },
  });
}
function engDone(ms: number, cost: number, prevented: boolean): EngineeredRun {
  return engineeredReducer(initialEngineered(), {
    type: "event",
    event: {
      event: "done",
      data: {
        ...common, side: "engineered", total_ms: ms, cache_hit: false, hallucination_prevented: prevented, mode: "demo",
        usage: { prompt_tokens: 1, completion_tokens: 1, tier: "8b", cost_usd: cost, source: "estimate" },
      },
    },
  });
}

describe("scoreboard", () => {
  it("accumulates latency, cost and hallucinations across races", () => {
    let b = addRace(emptyScoreboard(), naiveDone(5000, 0.003), engDone(12, 0, false));
    b = addRace(b, naiveDone(4000, 0.002), engDone(1000, 0.0005, true));
    expect(b.races).toBe(2);
    expect(b.latencySavedMs).toBe(5000 - 12 + 4000 - 1000);
    expect(b.costSavedUsd).toBeCloseTo(0.003 + 0.0015);
    expect(b.hallucinationsPrevented).toBe(1);
  });

  it("can go negative: engineered spends more on the hallucination trap, and says so", () => {
    const b = addRace(emptyScoreboard(), naiveDone(5000, 0.003), engDone(6000, 0.03, true));
    expect(b.costSavedUsd).toBeLessThan(0);
    expect(b.latencySavedMs).toBe(-1000);
  });

  it("ignores unfinished races", () => {
    const b = addRace(emptyScoreboard(), initialNaive(), engDone(1, 0, false));
    expect(b).toEqual(emptyScoreboard());
  });

  it("parses persisted state defensively", () => {
    expect(parseScoreboard(null)).toEqual(emptyScoreboard());
    expect(parseScoreboard("not json")).toEqual(emptyScoreboard());
    expect(parseScoreboard('{"races":"x","costSavedUsd":2}')).toMatchObject({ races: 0, costSavedUsd: 2 });
  });
});

describe("highlight", () => {
  it("splits text into flagged and plain segments", () => {
    const segs = segmentize("abc DEF ghi", [{ span: [4, 7], reason: "bad" }]);
    expect(segs).toEqual([
      { text: "abc ", reasons: [] },
      { text: "DEF", reasons: ["bad"] },
      { text: " ghi", reasons: [] },
    ]);
  });

  it("merges overlapping spans, clamps out-of-range ones and drops empty ones", () => {
    const segs = segmentize("0123456789", [
      { span: [2, 6], reason: "a" },
      { span: [4, 8], reason: "b" },
      { span: [8, 99], reason: "c" },
      { span: [5, 5], reason: "empty" },
    ]);
    expect(segs.map((s) => s.text).join("")).toBe("0123456789");
    expect(segs.find((s) => s.reasons.includes("a"))).toMatchObject({ text: "234567", reasons: ["a", "b"] });
    expect(segs.at(-1)).toMatchObject({ text: "89", reasons: ["c"] });
  });

  it("returns the text untouched when nothing is flagged", () => {
    expect(segmentize("hello", [])).toEqual([{ text: "hello", reasons: [] }]);
  });

  it("extracts bold runs", () => {
    expect(inlineBold("a **b** c")).toEqual([
      { text: "a ", bold: false },
      { text: "b", bold: true },
      { text: " c", bold: false },
    ]);
  });
});

describe("format", () => {
  it("formats ms and dollars at the scales the UI needs", () => {
    expect(fmtMs(7.13)).toBe("7.1 ms");
    expect(fmtMs(450)).toBe("450 ms");
    expect(fmtMs(4210)).toBe("4.21 s");
    expect(fmtUsd(0)).toBe("$0.00");
    expect(fmtUsd(0.00055)).toBe("$0.0006");
    expect(fmtUsd(0.000012)).toBe("$0.000012");
  });
});
