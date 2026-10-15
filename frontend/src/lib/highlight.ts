import type { UngroundedClaim } from "./types";

export interface Segment {
  text: string;
  /** Reasons the segment is flagged (merged when claims overlap); empty for plain text. */
  reasons: string[];
}

/**
 * Split `text` into plain and flagged segments from the backend's character spans.
 * Spans are clamped to the text, overlaps are merged (their reasons are combined), and empty spans are dropped.
 */
export function segmentize(text: string, claims: UngroundedClaim[]): Segment[] {
  const spans = claims
    .map((c) => ({ start: Math.max(0, c.span[0]), end: Math.min(text.length, c.span[1]), reason: c.reason }))
    .filter((s) => s.end > s.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);

  const merged: { start: number; end: number; reasons: string[] }[] = [];
  for (const s of spans) {
    const last = merged[merged.length - 1];
    if (last && s.start < last.end) {
      last.end = Math.max(last.end, s.end);
      if (!last.reasons.includes(s.reason)) last.reasons.push(s.reason);
    } else {
      merged.push({ start: s.start, end: s.end, reasons: [s.reason] });
    }
  }

  const out: Segment[] = [];
  let cursor = 0;
  for (const m of merged) {
    if (m.start > cursor) out.push({ text: text.slice(cursor, m.start), reasons: [] });
    out.push({ text: text.slice(m.start, m.end), reasons: m.reasons });
    cursor = m.end;
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor), reasons: [] });
  return out;
}

/** Split a string into bold (**x**) and plain parts: a deliberately tiny subset of markdown. */
export function inlineBold(text: string): { text: string; bold: boolean }[] {
  const parts: { text: string; bold: boolean }[] = [];
  const re = /\*\*([^*]+)\*\*/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index), bold: false });
    parts.push({ text: m[1] ?? "", bold: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), bold: false });
  return parts;
}
