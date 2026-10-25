import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { lensOf } from "@/lib/brand";
import { passageLineIndices } from "@/lib/citations";
import { compareRuns, correctAnswerSummary, inputRatio, sentTokens } from "@/lib/compare";
import {
  B2B_DOMAIN,
  HERO_PROMPTS,
  INJECTION_PROMPTS,
  STATIC_DOMAINS,
  TIER1_PROMPTS,
  cachePreset,
  findDomain,
  heroPreset,
  orderedPresets,
} from "@/lib/domains";
import { buildScenario } from "@/lib/fixtures/scenarios";
import { fmtTokens } from "@/lib/format";
import {
  engineeredReducer,
  initialEngineered,
  initialNaive,
  naiveReducer,
  type Action,
  type EngineeredRun,
  type NaiveRun,
} from "@/lib/reducer";
import { addRace, emptyScoreboard } from "@/lib/scoreboard";
import { VISITED_KEY, markVisited, newRaceId, readVisited, shouldShowNudge, type KV } from "@/lib/session";
import type { Domain, RaceEvent, RaceRequest, Side } from "@/lib/types";

const contractPath = path.resolve(__dirname, "../../../docs/contract-v2.md");
const doc = existsSync(contractPath) ? readFileSync(contractPath, "utf8") : "";

describe("verbatim prompt cards", () => {
  const all: [string, string][] = [
    ...Object.entries(HERO_PROMPTS),
    ...Object.entries(TIER1_PROMPTS).filter(([d]) => d !== "b2b_sla"),
    ...Object.entries(INJECTION_PROMPTS).filter(([d]) => d !== "b2b_sla"),
  ];

  it.skipIf(!doc)("every non-legacy prompt appears character-for-character in docs/contract-v2.md", () => {
    for (const [domain, text] of all) {
      expect(doc.includes(text), `${domain}: ${text.slice(0, 50)}`).toBe(true);
    }
  });

  it("the hero cards render the exact hero prompt for each domain", () => {
    for (const d of STATIC_DOMAINS) {
      expect(heroPreset(d)?.query).toBe(HERO_PROMPTS[d.id]);
    }
  });

  it("pins key phrases of the approved revised travel prompt", () => {
    expect(HERO_PROMPTS.travel_appr).toContain("I am travelling as 1 passenger.");
    expect(HERO_PROMPTS.travel_appr).toContain("$35 fee for each of my 2 checked bags");
  });

  it("every domain has exactly three cards in trap / router / injection order", () => {
    for (const d of STATIC_DOMAINS) {
      expect(orderedPresets(d).map((p) => p.kind)).toEqual(["hallucination_trap", "tier1_router", "prompt_injection"]);
    }
  });

  it("b2b keeps legacy preset ids", () => {
    const b2b = findDomain(STATIC_DOMAINS, "b2b_sla");
    expect(b2b.presets.map((p) => p.id)).toEqual(["hallucination_trap", "tier1_triage", "prompt_injection"]);
  });
});

describe("domain switching", () => {
  it("each domain swaps all three cards for distinct prompts", () => {
    const sets = STATIC_DOMAINS.map((d) => orderedPresets(d).map((p) => p.query).join("|"));
    expect(new Set(sets).size).toBe(STATIC_DOMAINS.length);
    expect(STATIC_DOMAINS[0]?.id).toBe("travel_appr"); // default
  });

  it("findDomain falls back to the static table when the backend omits a domain", () => {
    expect(findDomain([], "nutrition").id).toBe("nutrition");
  });

  it("the cache test uses the active domain's hero paraphrase", () => {
    for (const d of STATIC_DOMAINS) {
      const c = cachePreset(d);
      expect(c?.kind).toBe("hallucination_trap");
      expect(c?.paraphrase).toBeTruthy();
    }
  });
});

describe("B2B nudge", () => {
  const mem = (initial?: string, failWrites = false): KV => {
    const data = new Map<string, string>(initial ? [[VISITED_KEY, initial]] : []);
    return {
      getItem: (k) => data.get(k) ?? null,
      setItem: (k, v) => {
        if (failWrites) throw new Error("blocked");
        data.set(k, v);
      },
    };
  };

  it("shows after a finished non-B2B race when b2b_sla is unvisited", () => {
    expect(shouldShowNudge({ raceFinished: true, domain: "travel_appr", visited: ["travel_appr"], dismissed: false })).toBe(true);
  });

  it("hides before the race finishes, in B2B, once visited, or once dismissed", () => {
    const base = { raceFinished: true, domain: "travel_appr" as Domain, visited: ["travel_appr"] as Domain[], dismissed: false };
    expect(shouldShowNudge({ ...base, raceFinished: false })).toBe(false);
    expect(shouldShowNudge({ ...base, domain: B2B_DOMAIN })).toBe(false);
    expect(shouldShowNudge({ ...base, visited: ["travel_appr", B2B_DOMAIN] })).toBe(false);
    expect(shouldShowNudge({ ...base, dismissed: true })).toBe(false);
  });

  it("persists the visited set and survives broken storage", () => {
    const store = mem();
    const v = markVisited("b2b_sla", markVisited("travel_appr", [], store), store);
    expect(v).toEqual(["travel_appr", "b2b_sla"]);
    expect(readVisited(store)).toEqual(["travel_appr", "b2b_sla"]);
    expect(markVisited("b2b_sla", v, store)).toBe(v); // idempotent
    expect(markVisited("nutrition", [], mem(undefined, true))).toEqual(["nutrition"]); // write throws, still returns
    expect(readVisited(mem("not json"))).toEqual([]);
    expect(readVisited(null)).toEqual([]);
  });

  it("race ids match the backend pattern", () => {
    expect(newRaceId()).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(newRaceId()).not.toBe(newRaceId());
  });
});

const common = (side: Side) => ({ run_id: "r", side, t_ms: 1 });
const ev = (e: RaceEvent): Action => ({ type: "event", event: e });

describe("reducers: v2 events", () => {
  it("meta captures provider, model and context; payload/verdict/status are stored", () => {
    let s = naiveReducer(initialNaive(), { type: "start" });
    s = naiveReducer(
      s,
      ev({
        event: "meta",
        data: {
          ...common("naive"),
          mode: "live",
          query: "q",
          preset_id: null,
          model: "llama-3.3-70b-versatile",
          fallback_reason: null,
          race_id: "race_abc12345",
          domain: "nutrition",
          provider: "groq",
          base_model: "llama-3.3-70b-versatile",
          model_mode: "70b",
          context_mode: "full_kb",
          kb_tokens: 3000,
        },
      }),
    );
    expect(s).toMatchObject({ provider: "groq", model: "llama-3.3-70b-versatile", kbTokens: 3000, tokenSource: "provider", raceId: "race_abc12345" });
    s = naiveReducer(s, ev({ event: "status", data: { ...common("naive"), phase: "queued", detail: "waiting", wait_ms: 500 } }));
    expect(s.statusHint?.phase).toBe("queued");
    s = naiveReducer(
      s,
      ev({
        event: "payload",
        data: {
          ...common("naive"),
          attempt: 1,
          model: "m",
          messages: [{ role: "user", content: "<b>x</b>" }],
          token_count: 3100,
          token_source: "provider",
          composition: [{ label: "KB", tokens: 3000 }],
        },
      }),
    );
    expect(s.payloads).toHaveLength(1);
    expect(s.statusHint).toBeNull(); // progress clears the hint
    s = naiveReducer(
      s,
      ev({
        event: "verdict",
        data: { ...common("naive"), correct: false, required: [{ label: "a", expected: "1", found: false }], forbidden_hits: [], key_applies: true },
      }),
    );
    expect(s.verdict?.correct).toBe(false);
  });

  it("a retried payload attempt replaces the same attempt and keeps order", () => {
    let s = initialEngineered();
    const p = (attempt: number, tokens: number): RaceEvent => ({
      event: "payload",
      data: { ...common("engineered"), attempt, model: "m", messages: [], token_count: tokens, token_source: "estimate", composition: [] },
    });
    s = engineeredReducer(s, ev(p(2, 700)));
    s = engineeredReducer(s, ev(p(1, 500)));
    s = engineeredReducer(s, ev(p(1, 510)));
    expect(s.payloads.map((x) => [x.attempt, x.token_count])).toEqual([
      [1, 510],
      [2, 700],
    ]);
    expect(s.tokenSource).toBe("estimate");
  });

  it("race_state degraded flags the run and forces demo/estimate", () => {
    const s = engineeredReducer(
      initialEngineered(),
      ev({ event: "race_state", data: { ...common("engineered"), degraded: true, reason: "rate_limited", provider: "simulator" } }),
    );
    expect(s).toMatchObject({ degraded: true, degradedReason: "rate_limited", mode: "demo", tokenSource: "estimate" });
  });

  it("done carries usage source and the degraded flag", () => {
    const s = naiveReducer(
      initialNaive(),
      ev({
        event: "done",
        data: {
          ...common("naive"),
          degraded: true,
          total_ms: 10,
          cache_hit: false,
          hallucination_prevented: false,
          mode: "demo",
          usage: { prompt_tokens: 1, completion_tokens: 1, tier: "70b", cost_usd: 0, source: "estimate" },
        },
      }),
    );
    expect(s).toMatchObject({ degraded: true, tokenSource: "estimate" });
  });
});

describe("scoreboard excludes degraded races", () => {
  const done = (degraded: boolean): RaceEvent => ({
    event: "done",
    data: {
      ...common("naive"),
      degraded,
      total_ms: 100,
      cache_hit: false,
      hallucination_prevented: false,
      mode: "demo",
      usage: { prompt_tokens: 1, completion_tokens: 1, tier: "70b", cost_usd: 0.01, source: "estimate" },
    },
  });
  const pair = (d: boolean) => ({
    n: naiveReducer(initialNaive(), ev(done(d))),
    e: engineeredReducer(initialEngineered(), ev(done(d))),
  });

  it("does not count a degraded pair, and counts a clean one", () => {
    const bad = pair(true);
    expect(addRace(emptyScoreboard(), bad.n, bad.e)).toEqual(emptyScoreboard());
    const good = pair(false);
    expect(addRace(emptyScoreboard(), good.n, good.e).races).toBe(1);
    // degraded via race_state on only one side still excludes the race
    const half = engineeredReducer(
      good.e,
      ev({ event: "race_state", data: { ...common("engineered"), degraded: true, reason: null, provider: "simulator" } }),
    );
    expect(addRace(emptyScoreboard(), good.n, half).races).toBe(0);
  });
});

// --- mock streams: every state demonstrable ---------------------------------------------------
type Flavor = "live" | "demo" | "degraded";
function playNaive(req: RaceRequest, flavor: Flavor): { s: NaiveRun; events: RaceEvent[] } {
  const events = buildScenario("naive", req, flavor).map((x) => x.event);
  return { s: events.reduce((acc, e) => naiveReducer(acc, ev(e)), initialNaive()), events };
}
function playEng(req: RaceRequest, flavor: Flavor): { s: EngineeredRun; events: RaceEvent[] } {
  const events = buildScenario("engineered", req, flavor).map((x) => x.event);
  return { s: events.reduce((acc, e) => engineeredReducer(acc, ev(e)), initialEngineered()), events };
}
const reqFor = (domain: Domain, kind: 0 | 1 | 2, extra: Partial<RaceRequest> = {}): RaceRequest => {
  const info = findDomain(STATIC_DOMAINS, domain);
  const p = orderedPresets(info)[kind];
  return { query: p?.query ?? "", preset_id: p?.id ?? null, domain, context_mode: "full_kb", model_mode: "70b", race_id: "race_12345678", ...extra };
};

describe("mock scenarios", () => {
  it("produces the right card kind for each domain hero and injection card", () => {
    const heroKinds: Record<Domain, string> = {
      travel_appr: "appr_claim",
      bc_tenancy_cra: "tenancy_tax",
      nutrition: "nutrition_audit",
      b2b_sla: "invoice_audit",
    };
    for (const d of STATIC_DOMAINS.map((x) => x.id)) {
      expect(playEng(reqFor(d, 0), "live").s.card?.kind).toBe(heroKinds[d]);
      expect(playEng(reqFor(d, 2), "live").s.card?.kind).toBe("secure_response");
    }
    expect(playEng(reqFor("b2b_sla", 1), "live").s.card?.kind).toBe("triage");
    expect(playEng(reqFor("travel_appr", 1), "live").s.card?.kind).toBe("faq");
  });

  it("live uses provider tokens; demo uses estimates (rendered with ~)", () => {
    const live = playNaive(reqFor("travel_appr", 0), "live").s;
    const demo = playNaive(reqFor("travel_appr", 0), "demo").s;
    expect(live.tokenSource).toBe("provider");
    expect(demo.tokenSource).toBe("estimate");
    expect(fmtTokens(1234, demo.tokenSource)).toBe("~1,234");
    expect(fmtTokens(1234, live.tokenSource)).toBe("1,234");
  });

  it("verdicts differ and deltas favour the engineered side on tokens", () => {
    const n = playNaive(reqFor("travel_appr", 0), "live").s;
    const e = playEng(reqFor("travel_appr", 0), "live").s;
    expect(n.verdict?.correct).toBe(false);
    expect(e.verdict?.correct).toBe(true);
    expect(correctAnswerSummary(e.verdict)).toContain("770.00 CAD");
    expect(compareRuns(n, e).tokens).toBeGreaterThan(0);
    expect(inputRatio(n, e) ?? 0).toBeGreaterThan(3);
    expect(sentTokens(n) ?? 0).toBeGreaterThan(3000);
  });

  it("context_mode none sends far fewer tokens on the naive side", () => {
    const full = playNaive(reqFor("travel_appr", 0), "live").s;
    const none = playNaive(reqFor("travel_appr", 0, { context_mode: "none" }), "live").s;
    expect(sentTokens(none) ?? 0).toBeLessThan((sentTokens(full) ?? 0) / 5);
  });

  it("paraphrase variant is an engineered cache hit with zero spend", () => {
    const e = playEng(reqFor("travel_appr", 0, { variant: "paraphrase" }), "live").s;
    expect(e.cacheHit).toBe(true);
    expect(e.costUsd).toBe(0);
  });

  it("degraded flavor emits status hints and race_state on both sides and ends demo/estimate", () => {
    const runs = [playNaive(reqFor("travel_appr", 0), "degraded"), playEng(reqFor("travel_appr", 0), "degraded")];
    for (const { s, events } of runs) {
      expect(events.some((x) => x.event === "status")).toBe(true);
      expect(events.some((x) => x.event === "race_state")).toBe(true);
      expect(s).toMatchObject({ degraded: true, mode: "demo", status: "done" });
    }
  });

  it("model auto routes tier-1 prompts to 8B on the engineered side only", () => {
    const e = playEng(reqFor("nutrition", 1, { model_mode: "auto" }), "live").s;
    const n = playNaive(reqFor("nutrition", 1, { model_mode: "auto" }), "live").s;
    expect(e.model).toBe("8B/70B routed");
    expect(n.model).toBe("llama-3.3-70b-versatile");
  });
});


describe("DualSight lens attribution", () => {
  it("labels a passage by which search ranked it", () => {
    expect(lensOf(0.81, 12.4)).toBe("both");
    expect(lensOf(null, 9.1)).toBe("exact");
    expect(lensOf(0.77, null)).toBe("meaning");
  });
});

describe("citation passage highlighting", () => {
  const doc = [
    "# Northwind SLA",
    "## Service credits",
    "Uptime below 99.5% earns a 10% credit.",
    "Uptime below 99.0% earns a 25% credit.",
    "## Support",
    "Support is bundled at no extra charge.",
  ].join("\n");

  it("marks the cited body lines and their section heading only", () => {
    const chunk = "Northwind SLA — Service credits\nUptime below 99.5% earns a 10% credit.\nUptime below 99.0% earns a 25% credit.";
    expect([...passageLineIndices(doc, chunk, "Service credits")].sort()).toEqual([1, 2, 3]);
  });

  it("handles packed and continued sections", () => {
    const chunk = "Northwind SLA — Service credits (cont.); Support\nSupport:\nSupport is bundled at no extra charge.";
    expect([...passageLineIndices(doc, chunk, "Service credits (cont.); Support")].sort()).toEqual([1, 4, 5]);
  });
});
