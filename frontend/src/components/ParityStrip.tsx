import { MODEL_LABEL, inputRatio, sentTokens } from "@/lib/compare";
import { fmtTokens } from "@/lib/format";
import type { EngineeredRun, NaiveRun } from "@/lib/reducer";
import type { ContextMode, DomainInfo, ModelMode } from "@/lib/types";
import { TokenMeter } from "./ui";

/** "Same documents, same model, different architecture" strip with live sent-to-model meters. */
export function ParityStrip({
  domain,
  modelMode,
  contextMode,
  naive,
  eng,
}: {
  domain: DomainInfo;
  modelMode: ModelMode;
  contextMode: ContextMode;
  naive: NaiveRun;
  eng: EngineeredRun;
}) {
  const a = sentTokens(naive);
  const b = sentTokens(eng);
  const max = Math.max(a ?? 0, b ?? 0, 1);
  const ratio = inputRatio(naive, eng);
  const kb =
    contextMode === "full_kb"
      ? `Same knowledge base (${domain.doc_count} docs, ~${domain.kb_tokens.toLocaleString("en-US")} tokens)`
      : "Knowledge base withheld from the naive side";
  const model = modelMode === "auto" ? "Naive 70B · Engineered routed 8B/70B" : MODEL_LABEL[modelMode];
  return (
    <section aria-label="Parity" className="rounded-lg border border-line bg-panel px-3 py-3">
      <p className="text-[13px]">
        <span className="text-mute">Both sides:</span> <span className="font-medium">{model}</span>
        <span className="text-faint"> · </span>
        <span className="font-medium">{kb}</span>
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <TokenMeter
          label="Naive: sent to model"
          tone="naive"
          value={a}
          max={max}
          display={a === null ? "waiting" : `${fmtTokens(a, naive.payloads[0]?.token_source ?? null)} tokens`}
        />
        <TokenMeter
          label="Engineered: sent to model"
          tone="eng"
          value={b}
          max={max}
          display={b === null ? "waiting" : `${fmtTokens(b, eng.payloads[0]?.token_source ?? null)} tokens`}
        />
      </div>
      {ratio !== null && ratio >= 1.05 && (
        <p className="mt-2 text-[11px] text-mute">
          Measured: with DualSight the engineered side sent <span className="num text-ink">{ratio.toFixed(1)}x</span> fewer
          input tokens. Input tokens are what you pay for on every question.
        </p>
      )}
    </section>
  );
}
