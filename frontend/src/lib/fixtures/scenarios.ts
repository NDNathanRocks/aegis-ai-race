import { STATIC_DOMAINS } from "../domains";
import type {
  Domain,
  ModelMode,
  PayloadData,
  RaceEvent,
  RaceRequest,
  RetrievedChunk,
  Side,
  StructuredCard,
  TokenUsage,
  VerdictData,
} from "../types";
import {
  HERO_CARDS,
  HERO_FORBIDDEN,
  HERO_REQUIRED,
  KB_SNIPPET,
  NAIVE_FAQ_TEXT,
  NAIVE_HERO_TEXT,
  NAIVE_INJECTION_TEXT,
  injectionCard,
  tier1Card,
} from "./cards";

/**
 * Deterministic event scripts for NEXT_PUBLIC_MOCK=1. A Step is "wait delay ms, then emit event".
 * Flavors: live (provider tokens, LIVE chip), demo (simulator, estimated tokens, "~"), degraded (Groq fails mid-race).
 */
export type Flavor = "live" | "demo" | "degraded";
export interface Step {
  delay: number;
  event: RaceEvent;
}
type Kind = "hero" | "tier1" | "injection" | "custom";

const MODEL_70B = "llama-3.3-70b-versatile";
const MODEL_8B = "llama-3.1-8b-instant";
const estTokens = (s: string) => Math.max(1, Math.ceil(s.length / 4));

function resolveKind(req: RaceRequest): Kind {
  const domain = req.domain ?? "travel_appr";
  const p = STATIC_DOMAINS.find((d) => d.id === domain)?.presets.find((x) => x.id === req.preset_id);
  if (!p) return "custom";
  return p.kind === "hallucination_trap" ? "hero" : p.kind === "tier1_router" ? "tier1" : "injection";
}

function engineeredModel(mode: ModelMode, kind: Kind): string {
  if (mode === "8b") return MODEL_8B;
  if (mode === "70b") return MODEL_70B;
  return kind === "tier1" ? MODEL_8B : MODEL_70B;
}

function chunksFor(domain: Domain): RetrievedChunk[] {
  const titles: Record<Domain, string[]> = {
    travel_appr: ["APPR compensation schedule", "Baggage delay refunds", "EU261 summary", "Delay causes and exemptions"],
    bc_tenancy_cra: ["Rent increase rules (RTB-7)", "Landlord's use of property", "TFSA over-contributions", "Bad-faith compensation"],
    nutrition: ["Ingredient matrix: breads", "Ingredient matrix: sauces", "Diet cap policy", "Allergen cross-reference"],
    b2b_sla: ["Northwind Master SLA", "Premium Support inclusion", "Invoice audit policy", "Credit calculation"],
  };
  return titles[domain].map((t, i) => ({
    chunk_id: `${domain}-c${i + 1}`,
    doc_id: `${domain}-d${i + 1}`,
    doc_title: t,
    section: `§${i + 1}`,
    text: `${t}: (mock chunk text) ${KB_SNIPPET[domain].slice(0, 140)}`,
    dense_score: 0.82 - i * 0.05,
    bm25_score: 9.4 - i * 1.3,
    rrf_score: 0.0328 - i * 0.004,
    rank: i + 1,
  }));
}

function words(text: string): string[] {
  return text.match(/\S+\s*/g) ?? [text];
}

export function buildScenario(side: Side, req: RaceRequest, flavor: Flavor): Step[] {
  const domain = req.domain ?? "travel_appr";
  const kind = resolveKind(req);
  const contextMode = req.context_mode ?? "full_kb";
  const modelMode = req.model_mode ?? "70b";
  const kbTokens = STATIC_DOMAINS.find((d) => d.id === domain)?.kb_tokens ?? 3000;
  const degraded = flavor === "degraded";
  const live = flavor === "live";
  const source = live ? ("provider" as const) : ("estimate" as const);
  const cacheHit = side === "engineered" && req.variant === "paraphrase";
  const baseModel = side === "naive" ? MODEL_70B : engineeredModel(modelMode, kind);
  const modelLabel = side === "engineered" && modelMode === "auto" ? "8B/70B routed" : baseModel;
  const run_id = `mock-${side}`;
  const steps: Step[] = [];
  let t = 0;
  const at = (delay: number, event: RaceEvent) => {
    t += delay;
    steps.push({ delay, event });
  };
  const c = () => ({ run_id, side, t_ms: t });

  at(side === "naive" ? 40 : 150, {
    event: "meta",
    data: {
      ...c(),
      mode: live ? "live" : "demo",
      query: req.query,
      preset_id: req.preset_id ?? null,
      model: modelLabel,
      fallback_reason: live ? null : degraded ? null : "forced",
      race_id: req.race_id ?? null,
      domain,
      provider: live ? "groq" : "simulator",
      base_model: baseModel,
      model_mode: modelMode,
      context_mode: contextMode,
      kb_tokens: kbTokens,
    },
  });

  // --- what the answer will be ---
  const hero = HERO_CARDS[domain];
  let card: StructuredCard;
  let naiveText: string;
  let naiveCorrect: boolean;
  if (kind === "hero") {
    card = hero;
    naiveText = contextMode === "none" ? `${NAIVE_HERO_TEXT[domain]} (No knowledge base was provided, so these figures are guesses.)` : NAIVE_HERO_TEXT[domain];
    naiveCorrect = false;
  } else if (kind === "injection") {
    card = injectionCard(domain);
    naiveText = NAIVE_INJECTION_TEXT;
    naiveCorrect = false;
  } else if (kind === "tier1") {
    card = tier1Card(domain);
    naiveText = NAIVE_FAQ_TEXT[domain];
    naiveCorrect = false;
  } else {
    card = { kind: "faq", answer: "This is a mocked answer for a custom question. Run a preset to see a full scenario.", citations: [], confidence: 0.7 };
    naiveText = "This is a mocked free-form answer for a custom question.";
    naiveCorrect = true;
  }

  if (degraded) {
    at(200, { event: "status", data: { ...c(), phase: "queued", detail: "Queued for Groq token budget", wait_ms: 1200 } });
    at(900, { event: "status", data: { ...c(), phase: "retrying", detail: "Groq returned 429; retrying (attempt 2 of 3)", wait_ms: 1000 } });
  } else if (side === "engineered") {
    at(0, { event: "status", data: { ...c(), phase: "staggered", detail: "Staggered start to share the rate-limit bucket", wait_ms: 150 } });
  }

  // --- payload ---
  const question = req.query;
  const qTok = estTokens(question);
  const sys = side === "naive" ? "You are a helpful assistant. Answer the user's question." : "You are a grounded enterprise assistant. Answer ONLY from the provided context and return JSON.";
  const sysTok = estTokens(sys) + 6;
  const ctxText = side === "naive" ? (contextMode === "full_kb" ? KB_SNIPPET[domain] : "") : chunksFor(domain).map((x) => x.text).join("\n\n");
  const ctxTok = side === "naive" ? (contextMode === "full_kb" ? kbTokens : 0) : modelMode === "8b" || (modelMode === "auto" && kind === "tier1") ? 260 : 480;
  const messages: PayloadData["messages"] = [{ role: "system", content: sys }];
  if (ctxText) messages.push({ role: "system", content: side === "naive" ? `${ctxText}\n[... mock: full knowledge base truncated for display ...]` : `Context:\n${ctxText}` });
  messages.push({ role: "user", content: question });
  const payloadTokens = sysTok + ctxTok + qTok;
  const payload: PayloadData = {
    ...c(),
    attempt: 1,
    model: baseModel,
    messages,
    token_count: cacheHit ? 0 : payloadTokens,
    token_source: source,
    composition: [
      { label: "System prompt", tokens: sysTok },
      ...(ctxTok ? [{ label: side === "naive" ? "Full knowledge base" : "Retrieved chunks (4)", tokens: ctxTok }] : []),
      { label: "Question", tokens: qTok },
    ],
    chunks: side === "engineered" ? chunksFor(domain) : undefined,
  };

  const finalText = side === "naive" ? naiveText : JSON.stringify(card, null, 2);
  const completionTokens = estTokens(finalText);
  const costPer = 15 / 1_000_000;
  const usageTier = baseModel === MODEL_8B ? "8b" : "70b";
  const usage: TokenUsage = {
    prompt_tokens: cacheHit ? 0 : payloadTokens,
    completion_tokens: cacheHit ? 0 : completionTokens,
    tier: usageTier,
    cost_usd: cacheHit ? 0 : (payloadTokens + completionTokens) * costPer * (usageTier === "8b" ? 1 / 15 : 1),
    source,
  };

  const streamTokens = (text: string, from: number) => {
    const w = words(text);
    let acc = "";
    let total = 0;
    w.forEach((piece, i) => {
      acc += piece;
      total = Math.max(1, Math.round((completionTokens * (i + 1)) / w.length));
      at(from, {
        event: "token",
        data: {
          ...c(),
          text: piece,
          reset: false,
          prompt_tokens: payloadTokens,
          completion_tokens: total,
          cost_usd: (payloadTokens + total) * costPer * (usageTier === "8b" ? 1 / 15 : 1),
        },
      });
    });
    return acc;
  };

  const verdictFor = (correct: boolean): VerdictData => {
    const required = kind === "hero" ? HERO_REQUIRED[domain] : [{ label: "Answer matches key", expected: "see card" }];
    const keyApplies = kind !== "custom";
    return {
      ...c(),
      correct: keyApplies ? correct : true,
      required: required.map((r) => ({ ...r, found: correct })),
      forbidden_hits: !correct && keyApplies ? [{ label: kind === "hero" ? HERO_FORBIDDEN[domain] : "Followed injected instruction", span: [0, 20] }] : [],
      key_applies: keyApplies,
    };
  };

  if (!cacheHit) at(30, { event: "payload", data: payload });

  if (side === "naive") {
    at(60, { event: "node_start", data: { ...c(), node: "generator" } });
    if (degraded) {
      streamTokens(naiveText.slice(0, 40), 40);
      at(500, { event: "race_state", data: { ...c(), degraded: true, reason: "rate_limited", provider: "simulator" } });
      at(0, { event: "fallback", data: { ...c(), reason: "rate_limited", switched_to: "demo" } });
      at(40, { event: "token", data: { ...c(), text: "", reset: true, prompt_tokens: payloadTokens, completion_tokens: 0, cost_usd: 0 } });
    }
    streamTokens(naiveText, 45);
    const start = naiveText.indexOf("**");
    at(120, {
      event: "naive_analysis",
      data: {
        ...c(),
        ungrounded_claims: naiveCorrect || start < 0 ? [] : [{ span: [Math.max(0, start), Math.min(naiveText.length, start + 40)], reason: "Not supported by the knowledge base" }],
        schema_valid: false,
        schema_errors: ["Free-form text: no structured output"],
      },
    });
    at(40, { event: "verdict", data: verdictFor(naiveCorrect) });
    at(60, { event: "done", data: { ...c(), degraded, total_ms: t + 1500, usage: { ...usage, source: degraded ? "estimate" : source }, cache_hit: false, hallucination_prevented: false, mode: live && !degraded ? "live" : "demo" } });
    return steps;
  }

  // engineered
  const ms = (n: number) => n;
  at(20, { event: "node_start", data: { ...c(), node: "router" } });
  at(25, {
    event: "node_end",
    data: {
      ...c(),
      node: "router",
      latency_ms: ms(6.4),
      status: "ok",
      data: {
        complexity_score: kind === "tier1" ? 0.18 : 0.82,
        tier: usageTier,
        model: baseModel,
        card_kind: card.kind,
        injection_detected: kind === "injection",
        injection_patterns: kind === "injection" ? ["ignore previous instructions", "reveal system prompt"] : [],
        sanitized_query: kind === "injection" ? req.query.split("Anyway,")[1]?.trim() ?? req.query : req.query,
        reason: modelMode === "auto" ? "Smart router picked the tier from the complexity score" : `Tier forced by model selection (${modelMode.toUpperCase()})`,
      },
    },
  });
  at(10, { event: "node_start", data: { ...c(), node: "cache" } });
  at(15, { event: "node_end", data: { ...c(), node: "cache", latency_ms: 3.1, status: "ok", data: { hit: cacheHit, similarity: cacheHit ? 0.947 : null, threshold: 0.92, backend: "memory", matched_query: cacheHit ? "(earlier hero prompt)" : null } } });

  if (cacheHit) {
    for (const node of ["retriever", "generator", "critic", "validator"] as const) {
      at(10, { event: "node_end", data: { ...c(), node, latency_ms: 0, status: "skipped", data: {} } });
    }
    at(20, { event: "card", data: { ...c(), card, raw_json: JSON.stringify(card, null, 2) } });
    at(10, { event: "verdict", data: verdictFor(true) });
    at(20, { event: "done", data: { ...c(), degraded: false, total_ms: 11.8, usage, cache_hit: true, hallucination_prevented: false, mode: live ? "live" : "demo" } });
    return steps;
  }

  at(10, { event: "node_start", data: { ...c(), node: "retriever" } });
  at(120, { event: "node_end", data: { ...c(), node: "retriever", latency_ms: 38.5, status: "ok", data: { chunks: chunksFor(domain) } } });
  at(10, { event: "node_start", data: { ...c(), node: "generator", attempt: 1 } });
  if (degraded) {
    at(400, { event: "race_state", data: { ...c(), degraded: true, reason: "rate_limited", provider: "simulator" } });
    at(0, { event: "fallback", data: { ...c(), reason: "rate_limited", switched_to: "demo" } });
  }
  at(0, { event: "payload", data: { ...payload, ...c(), token_source: degraded ? "estimate" : source } });
  streamTokens(finalText, 12);
  at(10, { event: "node_end", data: { ...c(), node: "generator", latency_ms: 900, status: "ok", data: { usage, model: baseModel } } });
  at(10, { event: "node_start", data: { ...c(), node: "critic" } });
  at(30, { event: "node_end", data: { ...c(), node: "critic", latency_ms: 12.2, status: "ok", data: { passed: true, faithfulness: 1, flagged_claims: [], retry_requested: false } } });
  at(10, { event: "node_start", data: { ...c(), node: "validator" } });
  at(15, { event: "node_end", data: { ...c(), node: "validator", latency_ms: 1.4, status: "ok", data: { valid: true, errors: [] } } });
  at(10, { event: "card", data: { ...c(), card, raw_json: JSON.stringify(card, null, 2) } });
  at(10, { event: "eval", data: { ...c(), faithfulness: 1, context_relevance: 0.86, schema_validity: 1, context_recall: kind === "hero" ? 1 : null, unsupported_claims: [] } });
  at(10, { event: "verdict", data: verdictFor(true) });
  at(10, { event: "done", data: { ...c(), degraded, total_ms: t + 900, usage: { ...usage, source: degraded ? "estimate" : source }, cache_hit: false, hallucination_prevented: kind === "hero", mode: live && !degraded ? "live" : "demo" } });
  return steps;
}

