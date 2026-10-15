/** TypeScript mirror of the backend SSE contract (see plan.md section 4 / backend/app/schemas.py). */

export type Side = "naive" | "engineered";
export type Tier = "8b" | "70b";
export type Mode = "live" | "demo";
export type PresetId = "hallucination_trap" | "semantic_cache" | "tier1_triage" | "prompt_injection";
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
  card_kind: "invoice_audit" | "triage" | "secure_response" | "faq";
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
  | { kind: "faq"; answer: string; citations: string[]; confidence: number };

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
  model: string;
  fallback_reason: string | null;
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
