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
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 font-mono text-[11px] leading-4 ${TONES[tone]} ${className}`}
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
        className="h-1.5 overflow-hidden rounded-full bg-line/70"
      >
        <div className={`h-full rounded-full transition-[width] duration-500 ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: Tone }) {
  const color = tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : tone === "warn" ? "text-warn" : "text-ink";
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wider text-mute">{label}</div>
      <div className={`truncate font-mono text-base tabular-nums ${color}`}>{value}</div>
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
