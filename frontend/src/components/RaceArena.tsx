"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { fetchDomains, getSessionId } from "@/lib/api";
import type { CitationFocus, CitationTarget } from "@/lib/citations";
import { B2B_DOMAIN, DEFAULT_DOMAIN, STATIC_DOMAINS, cachePreset, findDomain, heroPreset } from "@/lib/domains";
import { MOCK, MOCK_FLAVORS, getMockFlavor, setMockFlavor } from "@/lib/mock";
import { engineeredReducer, initialEngineered, initialNaive, naiveReducer } from "@/lib/reducer";
import { addRace, emptyScoreboard, parseScoreboard, type Scoreboard as Board } from "@/lib/scoreboard";
import { markVisited, newRaceId, readVisited, shouldShowNudge } from "@/lib/session";
import type { ContextMode, Domain, DomainInfo, DomainPreset, ModelMode, PresetId, RaceRequest } from "@/lib/types";
import { TOUR } from "@/lib/brand";
import { useEmbedResize } from "@/lib/useEmbedResize";
import { useTour } from "@/lib/useTour";
import { useRace, useRunClock } from "@/lib/useRace";
import { B2BNudge, DegradedBanner } from "./Banners";
import { DomainSwitcher } from "./DomainSwitcher";
import { EngineeredPanel } from "./EngineeredPanel";
import { KnowledgeDrawer } from "./KnowledgeDrawer";
import { NaivePanel } from "./NaivePanel";
import { ParityStrip } from "./ParityStrip";
import { PayloadDrawer } from "./PayloadDrawer";
import { PromptCards, PromptEditor } from "./PromptCards";
import { RaceConfigBar } from "./RaceConfigBar";
import { Scoreboard } from "./Scoreboard";
import { PitchTour } from "./PitchTour";
import { ValuePitch } from "./ValuePitch";
import { VerdictBar } from "./VerdictBar";

const BOARD_KEY = "aegis:scoreboard";
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

interface LastRun {
  presetId: PresetId | null;
  variant: "primary" | "paraphrase";
  domain: Domain;
  query: string;
}

export function RaceArena() {
  const embed = useSearchParams().get("embed") === "true";
  const naive = useRace("naive", naiveReducer, initialNaive);
  const eng = useRace("engineered", engineeredReducer, initialEngineered);
  const naiveClock = useRunClock(naive.state.status, naive.state.totalMs);
  const engClock = useRunClock(eng.state.status, eng.state.totalMs);

  const rootRef = useRef<HTMLDivElement>(null);
  const configRef = useRef<HTMLElement>(null);
  const payloadRef = useRef<HTMLDivElement>(null);

  const [domains, setDomains] = useState<DomainInfo[]>(STATIC_DOMAINS);
  const [domainId, setDomainId] = useState<Domain>(DEFAULT_DOMAIN);
  const [contextMode, setContextMode] = useState<ContextMode>("full_kb");
  const [modelMode, setModelMode] = useState<ModelMode>("70b");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<PresetId | null>(null);
  const [board, setBoard] = useState<Board>(emptyScoreboard);
  const [kbOpen, setKbOpen] = useState(false);
  const [kbFocus, setKbFocus] = useState<CitationFocus | null>(null);
  const openCitation = useCallback((c: CitationTarget) => {
    setKbFocus({ ...c, nonce: Date.now() });
    setKbOpen(true);
  }, []);
  const [payloadOpen, setPayloadOpen] = useState(false);
  const [lastRun, setLastRun] = useState<LastRun | null>(null);
  const [visited, setVisited] = useState<Domain[]>([]);
  const [nudgeDismissed, setNudgeDismissed] = useState(false);
  const [, setMockTick] = useState(0);
  const sessionId = useRef<string>("");
  const runSeq = useRef(0);
  const scoredSeq = useRef(0);
  const chain = useRef(0); // invalidates an in-flight "cache test" sequence when the user starts something else

  const domain = useMemo(() => findDomain(domains, domainId), [domains, domainId]);

  // --- bootstrap -------------------------------------------------------------------------------
  useEffect(() => {
    sessionId.current = getSessionId();
    try {
      setBoard(parseScoreboard(window.sessionStorage.getItem(BOARD_KEY)));
    } catch {
      /* storage unavailable: start with an empty board */
    }
    setVisited(readVisited());
    const ctl = new AbortController();
    fetchDomains(ctl.signal)
      .then((d) => {
        if (Array.isArray(d) && d.length) setDomains(d);
      })
      .catch(() => {
        /* keep the static fallback */
      });
    return () => ctl.abort();
  }, []);

  useEffect(() => {
    document.documentElement.dataset.embed = embed ? "true" : "false";
  }, [embed]);

  // The active domain counts as visited (sessionStorage, try/catch inside).
  useEffect(() => {
    setVisited((v) => markVisited(domainId, v));
  }, [domainId]);

  // --- scoring ----------------------------------------------------------------------------------
  useEffect(() => {
    if (naive.state.status !== "done" || eng.state.status !== "done") return;
    if (scoredSeq.current === runSeq.current) return;
    scoredSeq.current = runSeq.current;
    setBoard((b) => {
      const next = addRace(b, naive.state, eng.state); // degraded races are excluded inside addRace
      try {
        window.sessionStorage.setItem(BOARD_KEY, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, [naive.state, eng.state]);

  const resetBoard = useCallback(() => {
    setBoard(emptyScoreboard());
    try {
      window.sessionStorage.removeItem(BOARD_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  // --- running races ----------------------------------------------------------------------------
  const busy = naive.state.status === "running" || eng.state.status === "running";
  const finished = naive.state.status === "done" && eng.state.status === "done";
  const degraded = naive.state.degraded || eng.state.degraded;
  const raceDomainMatches = lastRun?.domain === domainId;

  const race = useCallback(
    async (q: string, presetId: PresetId | null, variant: "primary" | "paraphrase") => {
      runSeq.current += 1;
      setLastRun({ presetId, variant, domain: domainId, query: q });
      const req: RaceRequest = {
        query: q,
        domain: domainId,
        context_mode: contextMode,
        model_mode: modelMode,
        race_id: newRaceId(), // one id for both sides: the server decides provider/mode once per race
        preset_id: presetId,
        variant,
        session_id: sessionId.current,
      };
      await Promise.allSettled([naive.start(req), eng.start(req)]);
    },
    [naive, eng, domainId, contextMode, modelMode],
  );

  /** Unedited preset text keeps its preset id (so the answer key applies); an edited prompt is a custom query. */
  const run = useCallback(() => {
    const q = query.trim();
    if (!q || busy) return;
    const preset = domain.presets.find((p) => p.id === selected && p.query === q);
    chain.current += 1;
    void race(q, preset ? preset.id : null, "primary");
  }, [query, busy, domain, selected, race]);

  const selectPreset = useCallback((p: DomainPreset) => {
    setSelected(p.id);
    setQuery(p.query);
  }, []);

  const switchDomain = useCallback((d: Domain, fillHero = false) => {
    chain.current += 1;
    setDomainId(d);
    const info = findDomain(domains, d);
    const hero = fillHero ? heroPreset(info) : undefined;
    setSelected(hero ? hero.id : null);
    setQuery(hero ? hero.query : "");
    setPayloadOpen(false);
    setKbOpen(false);
    setKbFocus(null);
  }, [domains]);

  const cache = cachePreset(domain);
  const runFollowUp = useCallback(() => {
    if (!cache?.paraphrase) return;
    chain.current += 1;
    void race(cache.paraphrase, cache.id, "paraphrase");
  }, [cache, race]);

  const runCacheTest = useCallback(async () => {
    if (!cache?.paraphrase) return;
    const token = ++chain.current;
    setSelected(cache.id);
    setQuery(cache.query);
    await race(cache.query, cache.id, "primary");
    await sleep(900);
    if (chain.current !== token) return;
    await race(cache.paraphrase, cache.id, "paraphrase");
  }, [cache, race]);

  // --- pitch mode -------------------------------------------------------------------------------
  const tour = useTour();
  const runTour = tour.start;
  const startTour = useCallback(() => {
    const hero = heroPreset(domain);
    const injection = domain.presets.find((p) => p.kind === "prompt_injection");
    const paraphrase = hero && cache?.id === hero.id ? cache.paraphrase : undefined;
    const steps = 2 + (hero ? 2 : 0) + (paraphrase ? 1 : 0) + (injection ? 1 : 0); // intro + end + optional steps
    // Wait a frame so freshly rendered sections (the verdict) exist before scrolling to them.
    const focus = (selector: string) =>
      window.setTimeout(() => document.querySelector(selector)?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    return runTour(async (t) => {
      let n = 0;
      chain.current += 1; // cancel any in-flight cache test
      t.show(++n, steps, TOUR.intro);
      focus('[aria-labelledby="pitch-title"]');
      if (!(await t.wait(9000))) return;
      if (hero) {
        t.show(++n, steps, TOUR.trap);
        setSelected(hero.id);
        setQuery(hero.query);
        focus("main");
        await race(hero.query, hero.id, "primary");
        if (!t.alive()) return;
        t.show(++n, steps, TOUR.verdict);
        focus('[aria-label="Verdict"]');
        if (!(await t.wait(10000))) return;
      }
      if (hero && paraphrase) {
        t.show(++n, steps, TOUR.cache);
        setQuery(paraphrase);
        focus("main");
        await race(paraphrase, hero.id, "paraphrase");
        if (!(await t.wait(7000))) return;
      }
      if (injection) {
        t.show(++n, steps, TOUR.injection);
        setSelected(injection.id);
        setQuery(injection.query);
        focus("main");
        await race(injection.query, injection.id, "primary");
        if (!(await t.wait(8000))) return;
      }
      t.show(steps, steps, TOUR.end);
      focus('[aria-label="Cumulative scoreboard"]');
    });
  }, [domain, cache, race, runTour]);

  // `?tour=1` starts pitch mode on load (for kiosks, screen recordings and shared demo links).
  const autoTour = useSearchParams().get("tour") === "1";
  const autoStarted = useRef(false);
  useEffect(() => {
    if (!autoTour || autoStarted.current) return;
    autoStarted.current = true;
    void startTour();
  }, [autoTour, startTour]);

  const followUpReady =
    !!cache && raceDomainMatches && lastRun?.presetId === cache.id && lastRun.variant === "primary" && eng.state.status === "done";

  const rerun = useCallback(() => {
    if (lastRun && !busy) void race(lastRun.query, lastRun.presetId, lastRun.variant);
  }, [lastRun, busy, race]);

  // --- B2B nudge --------------------------------------------------------------------------------
  const showNudge = shouldShowNudge({
    raceFinished: finished && raceDomainMatches,
    domain: domainId,
    visited,
    dismissed: nudgeDismissed,
  });
  const goB2B = useCallback(() => {
    switchDomain(B2B_DOMAIN, true);
    requestAnimationFrame(() => {
      configRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      configRef.current?.focus({ preventScroll: true });
    });
  }, [switchDomain]);

  // --- payload drawer ---------------------------------------------------------------------------
  const togglePayload = useCallback(() => setPayloadOpen((o) => !o), []);
  useEffect(() => {
    if (payloadOpen) payloadRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [payloadOpen]);

  // --- embed: keep the host iframe sized to the content -----------------------------------------
  useEmbedResize(rootRef, embed, [
    payloadOpen,
    kbOpen,
    degraded,
    showNudge,
    domainId,
    selected,
    finished,
    naive.state.statusHint,
    eng.state.statusHint,
    lastRun,
  ]);

  const retrievedDocIds = useMemo(() => Array.from(new Set(eng.state.chunks.map((c) => c.doc_id))), [eng.state.chunks]);
  const configLocked = busy;

  return (
    <div
      ref={rootRef}
      className={`${embed ? "px-2 py-2" : "mx-auto max-w-[1500px] px-4 py-6 sm:px-6"} ${tour.active ? "pb-48 sm:pb-36" : ""}`}
    >
      {!embed && (
        <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="num text-[11px] uppercase tracking-[0.2em] text-eng">Live architecture race</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">
              <span className="text-naive">Naive AI</span> <span className="text-mute">vs.</span>{" "}
              <span className="text-eng">Engineered AI</span>
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-mute">
              Same question, same model, two architectures, streamed side by side. Pick a domain and a prompt, then watch
              where a raw LLM wrapper breaks and what a production pipeline does about it.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void startTour()}
            disabled={busy || tour.active}
            className="min-h-[44px] shrink-0 self-start rounded-lg border border-eng/50 bg-eng/10 px-4 text-sm font-semibold text-eng transition-colors hover:bg-eng/20 disabled:cursor-not-allowed disabled:opacity-40 sm:self-auto"
          >
            ▶ Pitch mode
          </button>
        </header>
      )}
      {!embed && <ValuePitch />}

      <div className="space-y-3">
        <DomainSwitcher domains={domains} active={domainId} disabled={busy} onSelect={(d) => switchDomain(d)} />
        <p className="text-xs text-mute">{domain.blurb}</p>
        <RaceConfigBar
          ref={configRef}
          contextMode={contextMode}
          modelMode={modelMode}
          disabled={configLocked}
          onContext={setContextMode}
          onModel={setModelMode}
        />
        {MOCK && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-line-strong px-3 py-2 text-xs text-mute">
            <label htmlFor="mock-flavor">Mock stream (NEXT_PUBLIC_MOCK=1)</label>
            <select
              id="mock-flavor"
              defaultValue={getMockFlavor()}
              onChange={(e) => {
                setMockFlavor(e.target.value as ReturnType<typeof getMockFlavor>);
                setMockTick((n) => n + 1);
              }}
              className="min-h-[44px] rounded-lg border border-line bg-panel px-2 text-ink"
            >
              {MOCK_FLAVORS.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>
        )}
        <PromptCards domain={domain} selected={selected} busy={busy} onSelect={selectPreset} onRun={run} />
        <PromptEditor
          domain={domain}
          value={query}
          busy={busy}
          cacheReady={!!cache?.paraphrase}
          followUpReady={followUpReady}
          kbOpen={kbOpen}
          onChange={(v) => {
            setQuery(v);
            if (selected && domain.presets.find((p) => p.id === selected)?.query !== v) setSelected(null);
          }}
          onRun={run}
          onCacheTest={() => void runCacheTest()}
          onFollowUp={runFollowUp}
          onToggleKb={() => {
            setKbFocus(null);
            setKbOpen((o) => !o);
          }}
        />
        <ParityStrip domain={domain} modelMode={modelMode} contextMode={contextMode} naive={naive.state} eng={eng.state} />
      </div>

      <div className="mt-4">{degraded && <DegradedBanner reason={naive.state.degradedReason ?? eng.state.degradedReason} busy={busy} onRerun={rerun} />}</div>

      <main className="grid gap-4 lg:grid-cols-2">
        <NaivePanel run={naive.state} elapsedMs={naiveClock} inspectOpen={payloadOpen} onInspect={togglePayload} />
        <EngineeredPanel run={eng.state} elapsedMs={engClock} inspectOpen={payloadOpen} onInspect={togglePayload} onCite={openCitation} />
      </main>

      <div ref={payloadRef}>
        <PayloadDrawer open={payloadOpen} naive={naive.state.payloads} engineered={eng.state.payloads} onClose={() => setPayloadOpen(false)} />
      </div>

      {raceDomainMatches && <VerdictBar naive={naive.state} eng={eng.state} />}

      {showNudge && <B2BNudge onGo={goB2B} onDismiss={() => setNudgeDismissed(true)} />}

      <div className="mt-4">
        <Scoreboard board={board} onReset={resetBoard} />
      </div>

      {!embed && (
        <footer className="mt-8 border-t border-line pt-4 text-xs text-mute">
          <p>
            DualSight Retrieval (BM25 + <span className="font-mono">bge-small</span> ONNX, fused with RRF), the semantic cache,
            Pydantic validation and the RAG-triad scoring always run for real. In <span className="text-warn">DEMO</span>{" "}
            mode only the LLM text is a deterministic simulation; with a Groq key it is live. Token counts prefixed with{" "}
            <span className="num">~</span> are estimates; unprefixed counts come from the provider. Cost is priced at a
            flat $15 per million tokens, with the 8B tier at 1/15 of the 70B price. Answers are checked against rules in
            code, not by an LLM judge. Demo knowledge bases; not legal, tax or medical advice.
          </p>
        </footer>
      )}

      {tour.view && (
        <PitchTour view={tour.view} paused={tour.paused} onPause={tour.togglePause} onNext={tour.next} onExit={tour.exit} />
      )}

      <KnowledgeDrawer
        domain={domainId}
        open={kbOpen}
        onClose={() => {
          setKbOpen(false);
          setKbFocus(null);
        }}
        retrievedDocIds={retrievedDocIds}
        focus={kbFocus}
      />
    </div>
  );
}
