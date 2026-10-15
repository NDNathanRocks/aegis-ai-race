import type { Mode } from "@/lib/types";
import { Badge } from "./ui";

const REASONS: Record<string, string> = {
  no_key: "No GROQ_API_KEY configured",
  forced: "Demo mode requested",
  rate_limited: "Groq rate limit reached",
  upstream_error: "Groq returned an error",
  timeout: "Groq timed out",
};

/** Always-visible honesty marker: is the LLM text real (Groq) or the deterministic simulator? */
export function ModeBadge({ mode, reason }: { mode: Mode | null; reason?: string | null }) {
  if (!mode) return null;
  if (mode === "live") return <Badge tone="good" title="Tokens streamed from the Groq API">● LIVE · Groq</Badge>;
  return (
    <Badge tone="warn" title={`${reason ? (REASONS[reason] ?? reason) + ". " : ""}LLM text is simulated; retrieval, caching, validation and scoring are real.`}>
      ◐ DEMO · simulated LLM
    </Badge>
  );
}
