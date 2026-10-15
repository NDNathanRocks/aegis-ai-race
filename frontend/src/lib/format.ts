export function fmtMs(ms: number | null): string {
  if (ms === null) return "-";
  const abs = Math.abs(ms);
  if (abs < 10) return `${ms.toFixed(1)} ms`;
  if (abs < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function fmtUsd(usd: number): string {
  const abs = Math.abs(usd);
  if (abs === 0) return "$0.00";
  if (abs < 0.0001) return `${usd < 0 ? "-" : ""}$${abs.toFixed(6)}`;
  if (abs < 1) return `${usd < 0 ? "-" : ""}$${abs.toFixed(4)}`;
  return `${usd < 0 ? "-" : ""}$${abs.toFixed(2)}`;
}

export function fmtPct(v: number | null): string {
  return v === null ? "n/a" : `${Math.round(v * 100)}%`;
}

export function fmtSigned(ms: number): string {
  return `${ms >= 0 ? "+" : "-"}${fmtMs(Math.abs(ms))}`;
}

export function money(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}
