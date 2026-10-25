"use client";

import type { TourView } from "@/lib/useTour";

/** Caption bar for pitch mode: pinned to the bottom of the viewport, below the drawers in the stacking order. */
export function PitchTour({
  view,
  paused,
  onPause,
  onNext,
  onExit,
}: {
  view: TourView;
  paused: boolean;
  onPause: () => void;
  onNext: () => void;
  onExit: () => void;
}) {
  const done = view.index >= view.total;
  return (
    <div
      role="region"
      aria-label="Pitch mode"
      aria-live="polite"
      className="fixed inset-x-0 bottom-0 z-20 border-t border-eng/40 bg-panel/95 px-4 py-3 shadow-[0_-8px_24px_rgba(0,0,0,0.35)] backdrop-blur sm:px-6"
    >
      <div className="mx-auto flex max-w-[1500px] flex-col gap-3 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <p className="num text-[10px] uppercase tracking-[0.2em] text-eng">
            Pitch mode · {Math.min(view.index, view.total)} / {view.total}
          </p>
          <p className="mt-0.5 text-sm font-semibold text-ink">{view.title}</p>
          <p className="mt-0.5 text-xs text-mute">{view.body}</p>
          <div className="mt-2 h-0.5 rounded-full bg-line" aria-hidden>
            <div className="h-full rounded-full bg-eng transition-all duration-300" style={{ width: `${(Math.min(view.index, view.total) / view.total) * 100}%` }} />
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          {!done && (
            <>
              <button type="button" onClick={onPause} className="min-h-[44px] rounded-lg border border-line px-3 text-xs text-ink hover:bg-raised">
                {paused ? "Resume" : "Pause"}
              </button>
              <button type="button" onClick={onNext} className="min-h-[44px] rounded-lg border border-line px-3 text-xs text-ink hover:bg-raised">
                Next ▸
              </button>
            </>
          )}
          <button
            type="button"
            onClick={onExit}
            className={`min-h-[44px] rounded-lg px-3 text-xs ${done ? "bg-eng font-semibold text-bg" : "border border-line text-mute hover:text-ink"}`}
          >
            {done ? "Finish" : "Exit"}
          </button>
        </div>
      </div>
    </div>
  );
}
