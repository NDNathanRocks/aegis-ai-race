import { describe, expect, it } from "vitest";
import { engineeredReducer, initialEngineered, initialNaive, naiveReducer, type Action } from "@/lib/reducer";
import type { DoneData, RaceEvent, TokenUsage } from "@/lib/types";

const common = { run_id: "r", side: "engineered" as const, t_ms: 1 };
const usage = (cost: number, tier: "8b" | "70b" = "70b"): TokenUsage => ({
  prompt_tokens: 10,
  completion_tokens: 5,
  tier,
  cost_usd: cost,
});
const ev = (e: RaceEvent): Action => ({ type: "event", event: e });
const done = (over: Partial<DoneData> = {}): RaceEvent => ({
  event: "done",
  data: { ...common, total_ms: 100, usage: usage(0.01), cache_hit: false, hallucination_prevented: false, mode: "demo", ...over },
});
const token = (text: string, p: number, c: number, cost: number, reset = false): RaceEvent => ({
  event: "token",
  data: { ...common, text, reset, prompt_tokens: p, completion_tokens: c, cost_usd: cost },
});

describe("naiveReducer", () => {
  it("accumulates text, replaces it on reset, and finishes with authoritative usage", () => {
    let s = naiveReducer(initialNaive(), { type: "start" });
    expect(s.status).toBe("running");
    s = naiveReducer(s, ev(token("Hel", 5, 1, 0.1)));
    s = naiveReducer(s, ev(token("lo", 5, 2, 0.2)));
    expect(s.text).toBe("Hello");
    s = naiveReducer(s, ev(token("fresh", 5, 1, 0.1, true)));
    expect(s.text).toBe("fresh");
    s = naiveReducer(s, ev(done({ total_ms: 4200 })));
    expect(s).toMatchObject({ status: "done", totalMs: 4200, costUsd: 0.01, completionTokens: 5 });
  });

  it("a fallback event flips the run to demo mode", () => {
    const s = naiveReducer(initialNaive(), ev({ event: "fallback", data: { ...common, reason: "rate_limited", switched_to: "demo" } }));
    expect(s).toMatchObject({ mode: "demo", fallbackReason: "rate_limited" });
  });

  it("start clears a previous run", () => {
    const dirty = naiveReducer(initialNaive(), ev(token("x", 1, 1, 1)));
    expect(naiveReducer(dirty, { type: "start" }).text).toBe("");
  });
});

describe("engineeredReducer", () => {
  const start = (node: "generator" | "critic" | "router"): RaceEvent => ({ event: "node_start", data: { ...common, node } });

  it("tracks node lifecycle and per-node latency", () => {
    let s = engineeredReducer(initialEngineered(), { type: "start" });
    s = engineeredReducer(s, ev(start("router")));
    expect(s.nodes.router.status).toBe("active");
    s = engineeredReducer(
      s,
      ev({
        event: "node_end",
        data: {
          ...common,
          node: "router",
          latency_ms: 3.2,
          status: "ok",
          data: {
            complexity_score: 0.1, tier: "8b", model: "m", card_kind: "faq", injection_detected: false,
            injection_patterns: [], sanitized_query: "q", reason: "r",
          },
        },
      }),
    );
    expect(s.nodes.router).toMatchObject({ status: "done", latencyMs: 3.2 });
    expect(s.router?.tier).toBe("8b");
  });

  it("marks skipped nodes on a cache hit without touching their data", () => {
    const s = engineeredReducer(
      initialEngineered(),
      ev({ event: "node_end", data: { ...common, node: "generator", latency_ms: 0, status: "skipped", data: {} } }),
    );
    expect(s.nodes.generator.status).toBe("skipped");
    expect(s.generator).toBeNull();
  });

  it("banks the first generator attempt so cost and tokens accumulate across a critic retry", () => {
    let s = engineeredReducer(initialEngineered(), { type: "start" });
    s = engineeredReducer(s, ev(start("generator")));
    s = engineeredReducer(s, ev(token("{a", 100, 50, 0.5)));
    expect(s.costUsd).toBeCloseTo(0.5);
    s = engineeredReducer(s, ev(start("generator"))); // retry
    s = engineeredReducer(s, ev(token("{b", 110, 60, 0.2, true)));
    expect(s.draft).toBe("{b");
    expect(s.promptTokens).toBe(100 + 110);
    expect(s.completionTokens).toBe(50 + 60);
    expect(s.costUsd).toBeCloseTo(0.7);
    expect(s.nodes.generator.runs).toBe(2);
  });

  it("records every critic verdict and the final done payload", () => {
    let s = initialEngineered();
    for (const passed of [false, true]) {
      s = engineeredReducer(
        s,
        ev({
          event: "node_end",
          data: {
            ...common, node: "critic", latency_ms: 0.2, status: passed ? "ok" : "error", attempt: passed ? 1 : 0,
            data: { passed, faithfulness: passed ? 1 : 0.8, flagged_claims: passed ? [] : ["20% is not stated"], retry_requested: !passed },
          },
        }),
      );
    }
    expect(s.critic.map((c) => c.passed)).toEqual([false, true]);
    s = engineeredReducer(s, ev(done({ cache_hit: true, hallucination_prevented: true, total_ms: 12 })));
    expect(s).toMatchObject({ status: "done", cacheHit: true, hallucinationPrevented: true, totalMs: 12 });
  });

  it("a stream error ends the run with a message", () => {
    const s = engineeredReducer(initialEngineered(), { type: "fail", message: "boom" });
    expect(s).toMatchObject({ status: "error", error: "boom" });
  });
});
