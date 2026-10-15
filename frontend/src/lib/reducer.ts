import type {
  CacheLookup,
  CriticVerdict,
  GeneratorInfo,
  Mode,
  NaiveAnalysisData,
  NodeId,
  RaceEvent,
  RetrievedChunk,
  RouterDecision,
  StructuredCard,
  TokenUsage,
  TriadScores,
  ValidatorResult,
} from "./types";

export type RunStatus = "idle" | "running" | "done" | "error";
export type NodeStatus = "idle" | "active" | "done" | "skipped" | "error";

export interface NodeState {
  status: NodeStatus;
  latencyMs: number | null;
  /** How many times the node has started (the generator/critic loop at most twice). */
  runs: number;
}

interface RunBase {
  status: RunStatus;
  mode: Mode | null;
  fallbackReason: string | null;
  error: string | null;
  promptTokens: number;
  completionTokens: number;
  costUsd: number;
  /** Authoritative server-side total, set when the run finishes. */
  totalMs: number | null;
  usage: TokenUsage | null;
}

export interface NaiveRun extends RunBase {
  text: string;
  analysis: NaiveAnalysisData | null;
}

export interface EngineeredRun extends RunBase {
  nodes: Record<NodeId, NodeState>;
  router: RouterDecision | null;
  cache: CacheLookup | null;
  chunks: RetrievedChunk[];
  draft: string;
  generator: GeneratorInfo | null;
  critic: CriticVerdict[];
  validation: ValidatorResult | null;
  card: StructuredCard | null;
  rawJson: string | null;
  triad: TriadScores | null;
  cacheHit: boolean;
  hallucinationPrevented: boolean;
  /** Token/cost totals already finished by earlier generator attempts (the current attempt streams on top). */
  banked: { prompt: number; completion: number; cost: number };
  current: { prompt: number; completion: number; cost: number };
}

export type Action =
  | { type: "start" }
  | { type: "event"; event: RaceEvent }
  | { type: "fail"; message: string };

const NODE_IDS: NodeId[] = ["router", "cache", "retriever", "generator", "critic", "validator"];

const base = (): RunBase => ({
  status: "idle",
  mode: null,
  fallbackReason: null,
  error: null,
  promptTokens: 0,
  completionTokens: 0,
  costUsd: 0,
  totalMs: null,
  usage: null,
});

export const initialNaive = (): NaiveRun => ({ ...base(), text: "", analysis: null });

export const initialEngineered = (): EngineeredRun => ({
  ...base(),
  nodes: Object.fromEntries(NODE_IDS.map((n) => [n, { status: "idle", latencyMs: null, runs: 0 }])) as Record<
    NodeId,
    NodeState
  >,
  router: null,
  cache: null,
  chunks: [],
  draft: "",
  generator: null,
  critic: [],
  validation: null,
  card: null,
  rawJson: null,
  triad: null,
  cacheHit: false,
  hallucinationPrevented: false,
  banked: { prompt: 0, completion: 0, cost: 0 },
  current: { prompt: 0, completion: 0, cost: 0 },
});

export function naiveReducer(state: NaiveRun, action: Action): NaiveRun {
  switch (action.type) {
    case "start":
      return { ...initialNaive(), status: "running" };
    case "fail":
      return { ...state, status: "error", error: action.message };
    case "event": {
      const e = action.event;
      switch (e.event) {
        case "meta":
          return { ...state, mode: e.data.mode, fallbackReason: e.data.fallback_reason };
        case "token":
          return {
            ...state,
            text: e.data.reset ? e.data.text : state.text + e.data.text,
            promptTokens: e.data.prompt_tokens,
            completionTokens: e.data.completion_tokens,
            costUsd: e.data.cost_usd,
          };
        case "fallback":
          return { ...state, mode: "demo", fallbackReason: e.data.reason };
        case "naive_analysis":
          return { ...state, analysis: e.data };
        case "done":
          return {
            ...state,
            status: "done",
            mode: e.data.mode,
            totalMs: e.data.total_ms,
            usage: e.data.usage,
            promptTokens: e.data.usage.prompt_tokens,
            completionTokens: e.data.usage.completion_tokens,
            costUsd: e.data.usage.cost_usd,
          };
        case "error":
          return { ...state, status: "error", error: e.data.message };
        default:
          return state;
      }
    }
  }
}

function withNode(state: EngineeredRun, node: NodeId, patch: Partial<NodeState>): EngineeredRun {
  return { ...state, nodes: { ...state.nodes, [node]: { ...state.nodes[node], ...patch } } };
}

export function engineeredReducer(state: EngineeredRun, action: Action): EngineeredRun {
  switch (action.type) {
    case "start":
      return { ...initialEngineered(), status: "running" };
    case "fail":
      return { ...state, status: "error", error: action.message };
    case "event": {
      const e = action.event;
      switch (e.event) {
        case "meta":
          return { ...state, mode: e.data.mode, fallbackReason: e.data.fallback_reason };
        case "node_start": {
          let next = state;
          // A second generator attempt: bank what the first one spent so totals keep accumulating.
          if (e.data.node === "generator" && state.nodes.generator.runs > 0) {
            next = {
              ...state,
              banked: {
                prompt: state.banked.prompt + state.current.prompt,
                completion: state.banked.completion + state.current.completion,
                cost: state.banked.cost + state.current.cost,
              },
              current: { prompt: 0, completion: 0, cost: 0 },
            };
          }
          const prev = next.nodes[e.data.node];
          return withNode(next, e.data.node, { status: "active", runs: prev.runs + 1 });
        }
        case "node_end": {
          const d = e.data;
          const status: NodeStatus = d.status === "ok" ? "done" : d.status === "skipped" ? "skipped" : "error";
          let next = withNode(state, d.node, { status, latencyMs: d.latency_ms });
          if (d.status === "skipped") return next;
          switch (d.node) {
            case "router":
              next = { ...next, router: d.data };
              break;
            case "cache":
              next = { ...next, cache: d.data, cacheHit: d.data.hit };
              break;
            case "retriever":
              next = { ...next, chunks: d.data.chunks };
              break;
            case "generator":
              next = { ...next, generator: d.data };
              break;
            case "critic":
              next = { ...next, critic: [...next.critic, d.data] };
              break;
            case "validator":
              next = { ...next, validation: d.data };
              break;
          }
          return next;
        }
        case "token": {
          const cur = { prompt: e.data.prompt_tokens, completion: e.data.completion_tokens, cost: e.data.cost_usd };
          const b = state.banked;
          return {
            ...state,
            draft: e.data.reset ? e.data.text : state.draft + e.data.text,
            current: cur,
            promptTokens: b.prompt + cur.prompt,
            completionTokens: b.completion + cur.completion,
            costUsd: b.cost + cur.cost,
          };
        }
        case "fallback":
          return { ...state, mode: "demo", fallbackReason: e.data.reason };
        case "card":
          return { ...state, card: e.data.card, rawJson: e.data.raw_json };
        case "eval":
          return { ...state, triad: e.data };
        case "done":
          return {
            ...state,
            status: "done",
            mode: e.data.mode,
            totalMs: e.data.total_ms,
            usage: e.data.usage,
            promptTokens: e.data.usage.prompt_tokens,
            completionTokens: e.data.usage.completion_tokens,
            costUsd: e.data.usage.cost_usd,
            cacheHit: e.data.cache_hit,
            hallucinationPrevented: e.data.hallucination_prevented,
          };
        case "error":
          return { ...state, status: "error", error: e.data.message };
        default:
          return state;
      }
    }
  }
}
