import type { ReactNode } from "react";

type Tone = "neutral" | "good" | "bad" | "warn" | "eng" | "naive";

const TONES: Record<Tone, string> = {
  neutral: "border-line text-mute bg-raised",
  good: "border-good/40 text-good bg-good/10",
  bad: "border-bad/40 text-bad bg-bad/10",
  warn: "border-warn/40 text-warn bg-warn/10",
  eng: "border-eng/40 text-eng bg-eng/10",
  naive: "border-naive/40 text-naive bg-naive/10",
};

export function Badge({
  tone = "neutral",
  children,
  title,
  className = "",
}: {
  tone?: Tone;
  children: ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-[11px] leading-4 tabular-nums ${TONES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

export function MeterBar({
  label,
  value,
  hint,
}: {
  label: string;
  value: number | null;
  hint?: string;
}) {
  const pct = value === null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  const color = value === null ? "bg-line" : value >= 0.85 ? "bg-good" : value >= 0.6 ? "bg-warn" : "bg-bad";
  return (
    <div title={hint}>
      <div className="mb-1 flex items-baseline justify-between text-[11px]">
        <span className="text-mute">{label}</span>
        <span className="font-mono text-ink">{value === null ? "n/a" : `${Math.round(pct)}%`}</span>
      </div>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        className="h-1 overflow-hidden rounded-sm bg-line"
      >
        <div className={`h-full rounded-sm transition-[width] duration-150 ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: Tone }) {
  const color = tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : tone === "warn" ? "text-warn" : "text-ink";
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wider text-mute">{label}</div>
      <div className={`truncate num text-base ${color}`}>{value}</div>
    </div>
  );
}

export function StatusDot({ status }: { status: "idle" | "active" | "done" | "skipped" | "error" }) {
  const map = {
    idle: "bg-line",
    active: "bg-warn animate-pulse",
    done: "bg-good",
    skipped: "bg-mute/50",
    error: "bg-bad",
  } as const;
  return <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${map[status]}`} />;
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-mute">{children}</div>;
}

/** Flat labelled token meter: 1px-bordered track, solid fill (no gradients, no glow). */
export function TokenMeter({
  label,
  value,
  max,
  display,
  tone,
}: {
  label: string;
  value: number | null;
  max: number;
  display: string;
  tone: "naive" | "eng";
}) {
  const pct = value === null || max <= 0 ? 0 : Math.max(2, Math.min(100, (value / max) * 100));
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-baseline justify-between gap-2 text-[11px]">
        <span className={tone === "naive" ? "text-naive" : "text-eng"}>{label}</span>
        <span className="num text-ink">{display}</span>
      </div>
      <div className="h-1.5 rounded-sm border border-line bg-bg">
        <div
          className={`h-full rounded-sm transition-[width] duration-150 ${tone === "naive" ? "bg-naive" : "bg-eng"}`}
          style={{ width: `${value === null ? 0 : pct}%` }}
        />
      </div>
    </div>
  );
}

/** Segmented radio group with 44px tap targets. */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: T;
  options: { id: T; label: string }[];
  onChange: (v: T) => void;
  disabled?: boolean;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2">
      {options.map((o) => {
        const on = o.id === value;
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            onClick={() => onChange(o.id)}
            className={`min-h-[44px] px-3 py-2 text-left text-[13px] transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50 ${
              on ? "bg-raised text-ink" : "bg-panel text-mute hover:text-ink"
            }`}
          >
            <span className={`mr-2 inline-block h-2 w-2 rounded-full border ${on ? "border-eng bg-eng" : "border-faint"}`} aria-hidden />
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function StatusHint({ hint }: { hint: { phase: string; detail: string; wait_ms: number } | null }) {
  if (!hint) return null;
  const word = hint.phase === "retrying" ? "Retrying" : hint.phase === "queued" ? "Queued" : "Staggered";
  return (
    <p role="status" className="flex items-center gap-2 border-b border-line bg-raised px-4 py-2 text-[11px] text-mute">
      <StatusDot status="active" />
      <span className="text-warn">{word}</span>
      <span className="min-w-0 flex-1 truncate">{hint.detail}</span>
      {hint.wait_ms > 0 && <span className="num text-faint">{(hint.wait_ms / 1000).toFixed(1)} s</span>}
    </p>
  );
}
