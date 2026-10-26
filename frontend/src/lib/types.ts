/** TypeScript mirror of the backend SSE contract (see plan.md section 4 / backend/app/schemas.py). */

export type Side = "naive" | "engineered";
export type Tier = "8b" | "70b";
export type Mode = "live" | "demo";
export type Domain = "travel_appr" | "bc_tenancy_cra" | "nutrition" | "b2b_sla";
export type ContextMode = "full_kb" | "none";
export type ModelMode = "70b" | "8b" | "auto";
export type Provider = "groq" | "simulator";
export type UsageSource = "provider" | "estimate";
/** Preset ids are domain-scoped strings, e.g. "travel_hallucination_trap". See GET /api/domains. */
export type PresetId = string;
export type CardKind =
  | "invoice_audit" | "triage" | "secure_response" | "faq" | "appr_claim" | "tenancy_tax" | "nutrition_audit";
export type NodeId = "router" | "cache" | "retriever" | "generator" | "critic" | "validator";

export interface Preset {
  id: PresetId;
  title: string;
  tagline: string;
  query: string;
  paraphrase: string | null;
  card_kind: string;
}

export interface RaceRequest {
  query: string;
  domain?: Domain;
  context_mode?: ContextMode;
  model_mode?: ModelMode;
  /** Same id on both sides' requests; the server decides provider/mode once per race. */
  race_id?: string;
  preset_id?: PresetId | null;
  variant?: "primary" | "paraphrase";
  force_demo?: boolean;
  session_id?: string;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  tier: Tier;
  cost_usd: number;
  /** "provider" = counted by Groq; "estimate" = ~4 chars/token (demo mode). Render estimates with a "~" prefix. */
  source: UsageSource;
}

export interface RetrievedChunk {
  chunk_id: string;
  doc_id: string;
  doc_title: string;
  section: string;
  text: string;
  dense_score: number | null;
  bm25_score: number | null;
  rrf_score: number;
  rank: number;
}

export interface RouterDecision {
  complexity_score: number;
  tier: Tier;
  model: string;
  card_kind: CardKind;
  injection_detected: boolean;
  injection_patterns: string[];
  sanitized_query: string;
  reason: string;
}

export interface CacheLookup {
  hit: boolean;
  similarity: number | null;
  threshold: number;
  backend: "redis" | "memory";
  matched_query: string | null;
  rejected?: string | null;
}

export interface CriticVerdict {
  passed: boolean;
  faithfulness: number;
  flagged_claims: string[];
  retry_requested: boolean;
}

export interface ValidatorResult {
  valid: boolean;
  errors: string[];
}

export interface GeneratorInfo {
  usage: TokenUsage;
  model: string;
}

export interface InvoiceLineFinding {
  line_item: string;
  billed_usd: number;
  expected_usd: number;
  discrepancy_usd: number;
  policy_clause: string;
}

export type StructuredCard =
  | {
      kind: "invoice_audit";
      vendor: string;
      invoice_id: string;
      verdict: "compliant" | "overbilled" | "underbilled" | "needs_review";
      findings: InvoiceLineFinding[];
      total_discrepancy_usd: number;
      billed_total_usd: number;
      approved_payout_usd: number;
      citations: string[];
    }
  | {
      kind: "triage";
      category: "billing" | "outage" | "access" | "security" | "other";
      priority: "P1" | "P2" | "P3" | "P4";
      summary: string;
      suggested_queue: string;
      citations: string[];
    }
  | {
      kind: "secure_response";
      answer: string;
      injection_blocked: boolean;
      blocked_patterns: string[];
      citations: string[];
    }
  | { kind: "faq"; answer: string; citations: string[]; confidence: number }
  | {
      kind: "appr_claim";
      carrier_size: "large" | "small";
      delay_hours: number;
      delay_cause: "within_control" | "within_control_safety" | "outside_control";
      passengers: number;
      delay_compensation_cad: number;
      baggage_refund_cad: number;
      total_cad: number;
      rejected_claims: { claim: string; reason: string }[];
      citations: string[];
    }
  | {
      kind: "tenancy_tax";
      current_rent_cad: number;
      allowed_increase_pct: number;
      max_increase_cad: number;
      max_new_rent_cad: number;
      proposed_increase_lawful: boolean;
      eviction_notice_valid: boolean;
      eviction_findings: string[];
      tfsa_excess_cad: number;
      tfsa_months: number;
      tfsa_penalty_cad: number;
      citations: string[];
    }
  | {
      kind: "nutrition_audit";
      lines: { item: string; kcal: number; protein_g: number; sodium_mg: number; allergens: string[] }[];
      total_kcal: number;
      total_protein_g: number;
      total_sodium_mg: number;
      allergens_present: string[];
      violations: string[];
      compliant: boolean;
      citations: string[];
    };

export interface TriadScores {
  faithfulness: number;
  context_relevance: number;
  schema_validity: number;
  context_recall: number | null;
  unsupported_claims: string[];
}

export interface UngroundedClaim {
  span: [number, number];
  reason: string;
}

interface Common {
  run_id: string;
  side: Side;
  t_ms: number;
}

export interface MetaData extends Common {
  mode: Mode;
  query: string;
  preset_id: PresetId | null;
  /** Display label of the model(s) in use, e.g. "llama-3.3-70b-versatile" or "8B/70B routed". */
  model: string;
  fallback_reason: string | null;
  // --- v2 ---
  race_id: string | null;
  domain: Domain;
  provider: Provider;
  base_model: string;
  model_mode: ModelMode;
  context_mode: ContextMode;
  /** Tokens of the full domain KB (what the naive side sends in full_kb mode). */
  kb_tokens: number;
}

/** Backpressure / retry visibility. Emitted instead of silently failing over. */
export interface StatusData extends Common {
  phase: "staggered" | "queued" | "retrying";
  detail: string;
  wait_ms: number;
}

/** Race-level provider state. If degraded, BOTH sides end in simulator mode and the race is excluded from the scoreboard. */
export interface RaceStateData extends Common {
  degraded: boolean;
  reason: string | null;
  provider: Provider;
}

/** The exact context sent to the model (Inspect Prompt & Context Tokens). Emitted before generation; re-emitted per retry attempt. */
export interface PayloadData extends Common {
  attempt: number;
  model: string;
  messages: { role: "system" | "user" | "assistant"; content: string }[];
  token_count: number;
  token_source: UsageSource;
  composition: { label: string; tokens: number }[];
  /** Engineered only: the retrieved chunks, in order. */
  chunks?: RetrievedChunk[];
}

/** Deterministic answer-key check (no LLM judge). Emitted on both sides after the answer is final. */
export interface VerdictData extends Common {
  correct: boolean;
  required: { label: string; expected: string; found: boolean }[];
  forbidden_hits: { label: string; span: [number, number] | null }[];
  /** False when the prompt was edited so the key could not be recomputed; only numeric grounding applied. */
  key_applies: boolean;
}
export interface NodeStartData extends Common {
  node: NodeId;
  attempt?: number;
}
export type NodeEndData = Common & { latency_ms: number; status: "ok" | "skipped" | "error"; attempt?: number } & (
    | { node: "router"; data: RouterDecision }
    | { node: "cache"; data: CacheLookup }
    | { node: "retriever"; data: { chunks: RetrievedChunk[] } }
    | { node: "generator"; data: GeneratorInfo }
    | { node: "critic"; data: CriticVerdict }
    | { node: "validator"; data: ValidatorResult }
  );
export interface SkippedNodeData extends Common {
  node: NodeId;
  latency_ms: number;
  status: "skipped";
  attempt?: number;
  data: Record<string, never>;
}
export interface TokenData extends Common {
  text: string;
  reset: boolean;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
}
export interface CardData extends Common {
  card: StructuredCard;
  raw_json: string;
  /** The retrieved passages the card cites (also present on a cache hit, when no retrieval ran). */
  sources?: RetrievedChunk[];
}
export type EvalData = Common & TriadScores;
export interface NaiveAnalysisData extends Common {
  ungrounded_claims: UngroundedClaim[];
  schema_valid: boolean;
  schema_errors: string[];
}
export interface FallbackData extends Common {
  reason: string;
  switched_to: "demo";
}
export interface DoneData extends Common {
  degraded?: boolean;
  total_ms: number;
  usage: TokenUsage;
  cache_hit: boolean;
  hallucination_prevented: boolean;
  mode: Mode;
}
export interface ErrorData extends Common {
  code: string;
  message: string;
  recoverable: boolean;
}

export type RaceEvent =
  | { event: "meta"; data: MetaData }
  | { event: "node_start"; data: NodeStartData }
  | { event: "node_end"; data: NodeEndData | SkippedNodeData }
  | { event: "token"; data: TokenData }
  | { event: "card"; data: CardData }
  | { event: "eval"; data: EvalData }
  | { event: "naive_analysis"; data: NaiveAnalysisData }
  | { event: "fallback"; data: FallbackData }
  | { event: "status"; data: StatusData }
  | { event: "race_state"; data: RaceStateData }
  | { event: "payload"; data: PayloadData }
  | { event: "verdict"; data: VerdictData }
  | { event: "done"; data: DoneData }
  | { event: "error"; data: ErrorData };

export const EVENT_NAMES: ReadonlySet<string> = new Set([
  "meta",
  "node_start",
  "node_end",
  "token",
  "card",
  "eval",
  "naive_analysis",
  "fallback",
  "status",
  "race_state",
  "payload",
  "verdict",
  "done",
  "error",
]);

export interface KbDocumentSummary {
  id: string;
  title: string;
  category: string;
  words: number;
}
export interface KbDocument extends Omit<KbDocumentSummary, "words"> {
  text: string;
}
export interface BackendConfig {
  mode: Mode;
  fallback_reason: string | null;
  cache_backend: "redis" | "memory";
  vector_backend: string;
  embedding_model: string;
  cache_threshold: number;
  usd_per_million_tokens: number;
}

// --- Domains (GET /api/domains) ---------------------------------------------------------------
export type PresetKind = "hallucination_trap" | "tier1_router" | "prompt_injection";
export interface DomainPreset {
  id: PresetId;
  kind: PresetKind;
  title: string;
  tagline: string;
  /** Full verbatim prompt, rendered on the card and loaded into the editor. */
  query: string;
  paraphrase: string | null;
  card_kind: CardKind;
}
export interface DomainInfo {
  id: Domain;
  title: string;
  emoji: string;
  blurb: string;
  kb_tokens: number;
  doc_count: number;
  presets: DomainPreset[];
}
