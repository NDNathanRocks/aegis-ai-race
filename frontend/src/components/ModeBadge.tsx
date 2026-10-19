import type { Mode, Provider } from "@/lib/types";
import { Badge } from "./ui";

const REASONS: Record<string, string> = {
  no_key: "No GROQ_API_KEY configured",
  forced: "Demo mode requested",
  rate_limited: "Groq rate limit reached",
  upstream_error: "Groq returned an error",
  timeout: "Groq timed out",
};

/** Always-visible honesty marker (live Groq vs. deterministic simulator) plus the provider/model chip. */
export function ModeBadge({
  mode,
  reason,
  provider,
  model,
}: {
  mode: Mode | null;
  reason?: string | null;
  provider?: Provider | null;
  model?: string | null;
}) {
  if (!mode) return null;
  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5">
      {mode === "live" ? (
        <Badge tone="good" title="Tokens streamed from the Groq API">● LIVE · Groq</Badge>
      ) : (
        <Badge
          tone="warn"
          title={`${reason ? (REASONS[reason] ?? reason) + ". " : ""}LLM text is simulated; retrieval, caching, validation and scoring are real.`}
        >
          ◐ DEMO · simulated LLM
        </Badge>
      )}
      {model && (
        <Badge title={`Provider: ${provider ?? (mode === "live" ? "groq" : "simulator")}`}>
          {provider ?? (mode === "live" ? "groq" : "simulator")} · {model}
        </Badge>
      )}
    </div>
  );
}
