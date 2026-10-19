"use client";

export function DegradedBanner({ reason, busy, onRerun }: { reason: string | null; busy: boolean; onRerun: () => void }) {
  return (
    <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warn/50 bg-warn/10 px-4 py-3 text-sm">
      <span>
        <strong className="font-semibold text-warn">Groq rate-limited{reason ? ` (${reason})` : ""}.</strong>{" "}
        <span className="text-ink">
          This race is not an apples-to-apples comparison: both sides finished in simulator mode and it is excluded from the scoreboard.
        </span>
      </span>
      <button
        type="button"
        onClick={onRerun}
        disabled={busy}
        className="min-h-[44px] rounded-lg border border-warn/60 px-4 text-[13px] text-warn transition-colors duration-150 hover:bg-warn/10 disabled:cursor-not-allowed disabled:opacity-40"
      >
        Re-run both
      </button>
    </div>
  );
}

export function B2BNudge({ onGo, onDismiss }: { onGo: () => void; onDismiss: () => void }) {
  return (
    <aside aria-label="Try the enterprise domain" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line-strong bg-raised px-4 py-3">
      <p className="min-w-0 flex-1 text-[13px]">
        <span className="font-semibold">Now try the enterprise case.</span>{" "}
        <span className="text-mute">The same architecture audits a vendor invoice against a Master SLA.</span>
      </p>
      <div className="flex gap-2">
        <button type="button" onClick={onGo} className="min-h-[44px] rounded-lg bg-eng px-4 text-[13px] font-semibold text-bg">
          Switch to B2B SLA ▸
        </button>
        <button type="button" onClick={onDismiss} aria-label="Dismiss" className="min-h-[44px] min-w-[44px] rounded-lg border border-line text-mute hover:text-ink">
          ✕
        </button>
      </div>
    </aside>
  );
}
