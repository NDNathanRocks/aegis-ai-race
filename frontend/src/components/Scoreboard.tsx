import { fmtMs, fmtUsd } from "@/lib/format";
import { costPerCorrect, type Scoreboard as Board, type SideTally } from "@/lib/scoreboard";
import { Stat } from "./ui";

export function Scoreboard({ board, onReset }: { board: Board; onReset: () => void }) {
  const lat = board.latencySavedMs;
  const cost = board.costSavedUsd;
  // Scaled projection makes sub-cent per-request savings legible.
  const perMillion = board.races > 0 ? (cost / board.races) * 1_000_000 : 0;
  const naiveCpc = costPerCorrect(board.naive);
  const engCpc = costPerCorrect(board.eng);
  const engBetter = board.judged > 0 && engCpc !== null && (naiveCpc === null || engCpc <= naiveCpc);
  return (
    <section aria-label="Cumulative scoreboard" className="rounded-lg border border-line bg-raised px-4 py-2.5">
      <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-6">
        <div className="col-span-2 sm:col-span-1 lg:col-span-2" title="Total spend divided by answers that passed the answer key. A cheap wrong answer still costs money.">
          <div className="text-[10px] uppercase tracking-wider text-mute">Cost per correct answer</div>
          <div className="mt-0.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <SideCost name="Naive" tone="text-naive" value={naiveCpc} t={board.naive} judged={board.judged} />
            <SideCost name="Engineered" tone="text-eng" value={engCpc} t={board.eng} judged={board.judged} highlight={engBetter} />
          </div>
        </div>
        <Stat
          label="Paid for wrong answers"
          value={
            board.judged === 0 ? "-" : `${fmtUsd(board.naive.wrongSpendUsd)} vs ${fmtUsd(board.eng.wrongSpendUsd)}`
          }
          tone={board.judged === 0 ? undefined : board.eng.wrongSpendUsd <= board.naive.wrongSpendUsd ? "good" : "warn"}
        />
        <Stat
          label="Total latency saved"
          value={`${lat >= 0 ? "" : "-"}${fmtMs(Math.abs(lat))}`}
          tone={board.races === 0 ? undefined : lat >= 0 ? "good" : "bad"}
        />
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
      <p className="mt-2 border-t border-line pt-2 text-[11px] text-mute" title={`Averages ${fmtUsd(perMillion)} per 1M requests.`}>
        Raw cost difference: {fmtUsd(cost)} {cost >= 0 ? "saved" : "extra"} by the engineered side @ $15/1M tokens. On hard
        questions it can spend more (retrieval plus a critic retry), which is why the board ranks cost per correct answer.
      </p>
    </section>
  );
}

function SideCost({
  name,
  tone,
  value,
  t,
  judged,
  highlight = false,
}: {
  name: string;
  tone: string;
  value: number | null;
  t: SideTally;
  judged: number;
  highlight?: boolean;
}) {
  const shown = judged === 0 ? "-" : value === null ? "no correct answer" : fmtUsd(value);
  return (
    <span className="num text-sm" title={`${t.correct} of ${judged} correct, ${fmtUsd(t.spendUsd)} spent`}>
      <span className={`text-[11px] ${tone}`}>{name}</span>{" "}
      <span className={highlight ? "text-good" : "text-ink"}>{shown}</span>{" "}
      {judged > 0 && (
        <span className="text-[11px] text-mute">
          ({t.correct}/{judged})
        </span>
      )}
    </span>
  );
}
