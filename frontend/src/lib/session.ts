import type { Domain } from "./types";
import { B2B_DOMAIN } from "./domains";

export const VISITED_KEY = "aegis:visited";

/** Minimal storage surface so the logic is testable without a DOM. */
export interface KV {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function defaultStore(): KV | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function readVisited(store: KV | null = defaultStore()): Domain[] {
  try {
    const raw = store?.getItem(VISITED_KEY);
    if (!raw) return [];
    const v: unknown = JSON.parse(raw);
    return Array.isArray(v) ? (v.filter((x) => typeof x === "string") as Domain[]) : [];
  } catch {
    return [];
  }
}

/** Returns the new set; persistence failures are swallowed (private windows, blocked storage). */
export function markVisited(domain: Domain, current: Domain[], store: KV | null = defaultStore()): Domain[] {
  if (current.includes(domain)) return current;
  const next = [...current, domain];
  try {
    store?.setItem(VISITED_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
  return next;
}

/**
 * B2B nudge: after a finished race in a non-B2B domain, while b2b_sla has not been visited this session.
 * Degraded races still count as "finished" for nudging purposes; the visitor has seen a full run.
 */
export function shouldShowNudge(opts: {
  raceFinished: boolean;
  domain: Domain;
  visited: Domain[];
  dismissed: boolean;
}): boolean {
  return opts.raceFinished && !opts.dismissed && opts.domain !== B2B_DOMAIN && !opts.visited.includes(B2B_DOMAIN);
}

/** One id per run, shared by both sides' requests. Matches the backend pattern ^[A-Za-z0-9_-]{8,64}$. */
export function newRaceId(): string {
  const rand =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "")
      : Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
  return `race_${rand.slice(0, 24)}`;
}
