import { buildScenario, type Flavor } from "./fixtures/scenarios";
import { STATIC_DOMAINS } from "./domains";
import type { DomainInfo, KbDocument, KbDocumentSummary, RaceEvent, RaceRequest, Side } from "./types";

/** NEXT_PUBLIC_MOCK=1 replaces the network with scripted event streams so every UI state is demonstrable offline. */
export const MOCK = process.env.NEXT_PUBLIC_MOCK === "1";

export const MOCK_FLAVORS: { id: Flavor; label: string }[] = [
  { id: "live", label: "Live (provider tokens)" },
  { id: "demo", label: "Demo (estimated, ~)" },
  { id: "degraded", label: "Degraded race" },
];

let flavor: Flavor = "live";
export const getMockFlavor = () => flavor;
export const setMockFlavor = (f: Flavor) => {
  flavor = f;
};

export async function mockStreamRace(
  side: Side,
  body: RaceRequest,
  onEvent: (e: RaceEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  for (const step of buildScenario(side, body, flavor)) {
    await new Promise<void>((resolve) => {
      const id = setTimeout(resolve, step.delay);
      signal?.addEventListener("abort", () => {
        clearTimeout(id);
        resolve();
      });
    });
    if (signal?.aborted) return;
    onEvent(step.event);
  }
}

export const mockDomains = (): DomainInfo[] => STATIC_DOMAINS;

export const mockDocs = (): KbDocumentSummary[] => [
  { id: "mock-1", title: "Mock knowledge base document", category: "mock", words: 120 },
];
export const mockDoc = (id: string): KbDocument => ({
  id,
  title: "Mock knowledge base document",
  category: "mock",
  text: "# Mock document\n\nThis is fixture text shown when NEXT_PUBLIC_MOCK=1.",
});
