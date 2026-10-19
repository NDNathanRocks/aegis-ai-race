import { fmtMs, fmtUsd } from "@/lib/format";
import type { Scoreboard as Board } from "@/lib/scoreboard";
import { Stat } from "./ui";

export function Scoreboard({ board, onReset }: { board: Board; onReset: () => void }) {
  const lat = board.latencySavedMs;
  const cost = board.costSavedUsd;
  // Scaled projection makes sub-cent per-request savings legible.
  const perMillion = board.races > 0 ? (cost / board.races) * 1_000_000 : 0;
  return (
    <div
      aria-label="Cumulative scoreboard"
      className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-lg border border-line bg-raised px-4 py-2.5 sm:grid-cols-4"
    >
      <Stat
        label="Total latency saved"
        value={`${lat >= 0 ? "" : "-"}${fmtMs(Math.abs(lat))}`}
        tone={board.races === 0 ? undefined : lat >= 0 ? "good" : "bad"}
      />
      <div title={`Simulated enterprise cost at $15 / 1M tokens. Averages ${fmtUsd(perMillion)} per 1M requests.`}>
        <Stat
          label="Cost saved @ $15/1M"
          value={fmtUsd(cost)}
          tone={board.races === 0 ? undefined : cost >= 0 ? "good" : "warn"}
        />
      </div>
      <Stat label="Hallucinations prevented" value={board.hallucinationsPrevented} tone={board.hallucinationsPrevented ? "good" : undefined} />
      <div className="flex items-end justify-between gap-2">
        <Stat label="Races counted" value={board.races} />
        <button
          onClick={onReset}
          disabled={board.races === 0}
          className="min-h-[44px] rounded px-2 text-[11px] text-mute underline-offset-2 hover:text-ink hover:underline disabled:opacity-30"
        >
          reset
        </button>
      </div>
    </div>
  );
}
