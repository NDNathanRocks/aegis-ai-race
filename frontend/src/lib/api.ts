import { API_URL } from "./sse";
import { MOCK, mockDoc, mockDocs, mockDomains } from "./mock";
import type { BackendConfig, Domain, DomainInfo, KbDocument, KbDocumentSummary, Preset } from "./types";

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, { signal, cache: "no-store" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${path}`);
  return (await resp.json()) as T;
}

export const fetchPresets = (signal?: AbortSignal) => getJson<Preset[]>("/api/presets", signal);
export const fetchConfig = (signal?: AbortSignal) => getJson<BackendConfig>("/api/config", signal);
export const fetchDomains = (signal?: AbortSignal) =>
  MOCK ? Promise.resolve<DomainInfo[]>(mockDomains()) : getJson<DomainInfo[]>("/api/domains", signal);

/** Domain-scoped KB listing; falls back to the legacy flat endpoint until the backend ships it. */
export async function fetchDocuments(domain: Domain, signal?: AbortSignal): Promise<KbDocumentSummary[]> {
  if (MOCK) return mockDocs();
  try {
    return await getJson<KbDocumentSummary[]>(`/api/kb/${domain}/documents`, signal);
  } catch (e) {
    if (signal?.aborted) throw e;
    return getJson<KbDocumentSummary[]>("/api/kb/documents", signal);
  }
}
export async function fetchDocument(domain: Domain, id: string, signal?: AbortSignal): Promise<KbDocument> {
  if (MOCK) return mockDoc(id);
  try {
    return await getJson<KbDocument>(`/api/kb/${domain}/documents/${encodeURIComponent(id)}`, signal);
  } catch (e) {
    if (signal?.aborted) throw e;
    return getJson<KbDocument>(`/api/kb/documents/${encodeURIComponent(id)}`, signal);
  }
}

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
