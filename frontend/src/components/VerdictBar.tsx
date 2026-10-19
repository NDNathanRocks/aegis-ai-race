import { compareRuns, correctAnswerSummary, missingLabels } from "@/lib/compare";
import { fmtMs, fmtUsd } from "@/lib/format";
import type { EngineeredRun, NaiveRun } from "@/lib/reducer";
import type { VerdictData } from "@/lib/types";
import { Badge } from "./ui";

function Side({ name, tone, verdict }: { name: string; tone: "naive" | "eng"; verdict: VerdictData | null }) {
  const color = tone === "naive" ? "text-naive" : "text-eng";
  if (!verdict) {
    return (
      <div className="min-w-0">
        <div className={`text-[11px] uppercase tracking-wider ${color}`}>{name}</div>
        <div className="text-xs text-mute">No verdict</div>
      </div>
    );
  }
  const miss = missingLabels(verdict);
  return (
    <div className="min-w-0">
      <div className={`text-[11px] uppercase tracking-wider ${color}`}>{name}</div>
      <div className="mt-0.5 flex items-center gap-2">
        <span className={`text-base font-semibold ${verdict.correct ? "text-good" : "text-bad"}`}>
          {verdict.correct ? "✓ Correct" : "✗ Incorrect"}
        </span>
      </div>
      {miss.length > 0 && <div className="text-[11px] text-mute">Missing: {miss.join(", ")}</div>}
      {verdict.forbidden_hits.map((h) => (
        <div key={h.label} className="text-[11px] text-bad">
          ✕ {h.label}
        </div>
      ))}
    </div>
  );
}

function Delta({ label, value, good }: { label: string; value: string; good: boolean | null }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wider text-mute">{label}</div>
      <div className={`num text-sm ${good === null ? "text-ink" : good ? "text-good" : "text-warn"}`}>{value}</div>
    </div>
  );
}

/** Verdict-first result row: correct answer vs naive vs engineered, with token / ms / $ deltas. */
export function VerdictBar({ naive, eng }: { naive: NaiveRun; eng: EngineeredRun }) {
  if (naive.status !== "done" || eng.status !== "done" || (!naive.verdict && !eng.verdict)) return null;
  const d = compareRuns(naive, eng);
  const answer = correctAnswerSummary(eng.verdict ?? naive.verdict);
  const keyApplies = (eng.verdict ?? naive.verdict)?.key_applies !== false;
  const signed = (n: number) => `${n >= 0 ? "-" : "+"}${Math.abs(n).toLocaleString("en-US")}`;
  return (
    <section aria-label="Verdict" className="mt-4 rounded-lg border border-line bg-panel px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Verdict</h2>
        <Badge title="Checked against rules in code, not by an LLM judge">rule-checked, no LLM judge</Badge>
      </div>
      <p className="mt-2 text-[13px]">
        <span className="text-mute">Correct answer: </span>
        {answer ?? <span className="text-mute">answer key not applicable to an edited prompt; numeric grounding only</span>}
      </p>
      {!keyApplies && <p className="mt-1 text-[11px] text-warn">Prompt differs from the preset, so only numeric grounding was applied.</p>}
      <div className="mt-3 grid gap-4 border-t border-line pt-3 sm:grid-cols-2">
        <Side name="Naive" tone="naive" verdict={naive.verdict} />
        <Side name="Engineered" tone="eng" verdict={eng.verdict} />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-3 border-t border-line pt-3">
        <Delta
          label="Tokens (eng vs naive)"
          value={d.tokens === 0 ? "0" : `${signed(d.tokens)}${eng.tokenSource === "estimate" || naive.tokenSource === "estimate" ? " (est.)" : ""}`}
          good={d.tokens === 0 ? null : d.tokens > 0}
        />
        <Delta label="Time" value={d.ms === null ? "-" : `${d.ms >= 0 ? "-" : "+"}${fmtMs(Math.abs(d.ms))}`} good={d.ms === null ? null : d.ms >= 0} />
        <Delta label="Cost" value={`${d.usd >= 0 ? "-" : "+"}${fmtUsd(Math.abs(d.usd))}`} good={d.usd >= 0} />
      </div>
      {(naive.degraded || eng.degraded) && <p className="mt-2 text-[11px] text-warn">Degraded race: shown for reference, not counted on the scoreboard.</p>}
    </section>
  );
}
