import { API_URL } from "./sse";
import type { BackendConfig, KbDocument, KbDocumentSummary, Preset } from "./types";

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, { signal, cache: "no-store" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${path}`);
  return (await resp.json()) as T;
}

export const fetchPresets = (signal?: AbortSignal) => getJson<Preset[]>("/api/presets", signal);
export const fetchConfig = (signal?: AbortSignal) => getJson<BackendConfig>("/api/config", signal);
export const fetchDocuments = (signal?: AbortSignal) => getJson<KbDocumentSummary[]>("/api/kb/documents", signal);
export const fetchDocument = (id: string, signal?: AbortSignal) =>
  getJson<KbDocument>(`/api/kb/documents/${encodeURIComponent(id)}`, signal);

export async function resetCache(sessionId: string): Promise<void> {
  await fetch(`${API_URL}/api/cache/reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
}

/** A per-tab id so one visitor's semantic cache never pre-warms another's demo. */
export function getSessionId(): string {
  const fallback = () => `s${Math.random().toString(36).slice(2, 12)}`;
  try {
    const existing = window.sessionStorage.getItem("aegis:session");
    if (existing) return existing;
    const id = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : fallback();
    window.sessionStorage.setItem("aegis:session", id);
    return id;
  } catch {
    return fallback();
  }
}
