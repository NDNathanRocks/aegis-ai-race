"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { fetchPresets, getSessionId } from "@/lib/api";
import { engineeredReducer, initialEngineered, initialNaive, naiveReducer } from "@/lib/reducer";
import { addRace, emptyScoreboard, parseScoreboard, type Scoreboard as Board } from "@/lib/scoreboard";
import { API_URL } from "@/lib/sse";
import type { Preset, PresetId } from "@/lib/types";
import { useRace, useRunClock } from "@/lib/useRace";
import { ControlBar } from "./ControlBar";
import { EngineeredPanel } from "./EngineeredPanel";
import { KnowledgeDrawer } from "./KnowledgeDrawer";
import { NaivePanel } from "./NaivePanel";
import { Scoreboard } from "./Scoreboard";

const BOARD_KEY = "aegis:scoreboard";
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

interface LastRun {
  presetId: PresetId | null;
  variant: "primary" | "paraphrase";
}

export function RaceArena() {
  const embed = useSearchParams().get("embed") === "true";
  const naive = useRace("naive", naiveReducer, initialNaive);
  const eng = useRace("engineered", engineeredReducer, initialEngineered);
  const naiveClock = useRunClock(naive.state.status, naive.state.totalMs);
  const engClock = useRunClock(eng.state.status, eng.state.totalMs);

  const [presets, setPresets] = useState<Preset[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [board, setBoard] = useState<Board>(emptyScoreboard);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [lastRun, setLastRun] = useState<LastRun | null>(null);
  const sessionId = useRef<string>("");
  const runSeq = useRef(0);
  const scoredSeq = useRef(0);
  const chain = useRef(0); // invalidates an in-flight "cache test" sequence when the user starts something else

  // --- bootstrap -------------------------------------------------------------------------------
  const load = useCallback(() => {
    setLoadError(null);
    const ctl = new AbortController();
    fetchPresets(ctl.signal)
      .then(setPresets)
      .catch(() => {
        if (!ctl.signal.aborted) setLoadError(`Cannot reach the backend at ${API_URL}.`);
      });
    return () => ctl.abort();
  }, []);

  useEffect(() => {
    sessionId.current = getSessionId();
    try {
      setBoard(parseScoreboard(window.sessionStorage.getItem(BOARD_KEY)));
    } catch {
      /* storage unavailable: start with an empty board */
    }
    return load();
  }, [load]);

  useEffect(() => {
    document.documentElement.dataset.embed = embed ? "true" : "false";
  }, [embed]);

  // Tell a host page how tall the arena is so its <iframe> can resize to fit.
  useEffect(() => {
    if (!embed || window.parent === window) return;
    const post = () => window.parent.postMessage({ type: "aegis:resize", height: document.documentElement.scrollHeight }, "*");
    const ro = new ResizeObserver(post);
    ro.observe(document.body);
    post();
    return () => ro.disconnect();
  }, [embed]);

  // --- scoring ----------------------------------------------------------------------------------
  useEffect(() => {
    if (naive.state.status !== "done" || eng.state.status !== "done") return;
    if (scoredSeq.current === runSeq.current) return;
    scoredSeq.current = runSeq.current;
    setBoard((b) => {
      const next = addRace(b, naive.state, eng.state);
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

  const race = useCallback(
    async (query: string, presetId: PresetId | null, variant: "primary" | "paraphrase") => {
      runSeq.current += 1;
      setLastRun({ presetId, variant });
      const req = { query, preset_id: presetId, variant, session_id: sessionId.current };
      await Promise.allSettled([naive.start(req), eng.start(req)]);
    },
    [naive, eng],
  );

  const runPreset = useCallback(
    (p: Preset) => {
      chain.current += 1;
      void race(p.query, p.id, "primary");
    },
    [race],
  );

  const runFollowUp = useCallback(() => {
    const p = presets?.find((x) => x.id === "semantic_cache");
    if (!p?.paraphrase) return;
    chain.current += 1;
    void race(p.paraphrase, p.id, "paraphrase");
  }, [presets, race]);

  const runCustom = useCallback(
    (q: string) => {
      chain.current += 1;
      void race(q, null, "primary");
    },
    [race],
  );

  const runCacheTest = useCallback(async () => {
    const p = presets?.find((x) => x.id === "semantic_cache");
    if (!p?.paraphrase) return;
    const token = ++chain.current;
    await race(p.query, p.id, "primary");
    await sleep(900);
    if (chain.current !== token) return;
    await race(p.paraphrase, p.id, "paraphrase");
  }, [presets, race]);

  const followUpReady =
    lastRun?.presetId === "semantic_cache" && lastRun.variant === "primary" && eng.state.status === "done";

  const retrievedDocIds = useMemo(() => Array.from(new Set(eng.state.chunks.map((c) => c.doc_id))), [eng.state.chunks]);

  return (
    <div className={embed ? "px-2 py-2" : "mx-auto max-w-[1500px] px-4 py-6 sm:px-6"}>
      {!embed && (
        <header className="mb-6">
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-eng">Live architecture race</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-4xl">
            <span className="text-naive">Naive AI</span> <span className="text-mute">vs.</span>{" "}
            <span className="text-eng">Engineered AI</span>
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-mute">
            Same question, two architectures, streamed side by side. One click on a challenge below and watch where a
            raw LLM wrapper breaks and what a production pipeline does about it.
          </p>
        </header>
      )}

      <div className="sticky top-0 z-20 -mx-2 mb-4 space-y-3 bg-bg/90 px-2 pb-3 pt-2 backdrop-blur sm:static sm:mx-0 sm:bg-transparent sm:p-0 sm:backdrop-blur-none">
        {presets ? (
          <ControlBar
            presets={presets}
            activePreset={lastRun?.presetId ?? null}
            busy={busy}
            followUpReady={followUpReady}
            drawerOpen={drawerOpen}
            onPreset={runPreset}
            onFollowUp={runFollowUp}
            onCustom={runCustom}
            onCacheTest={() => void runCacheTest()}
            onToggleDrawer={() => setDrawerOpen((o) => !o)}
          />
        ) : loadError ? (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-sm">
            <span className="text-bad">{loadError} Start it with <code className="font-mono">uvicorn app.main:app</code>.</span>
            <button onClick={load} className="rounded-lg border border-bad/50 px-3 py-1 text-xs hover:bg-bad/10">
              Retry
            </button>
          </div>
        ) : (
          <div aria-busy className="h-24 animate-pulse rounded-xl bg-panel" />
        )}
        <Scoreboard board={board} onReset={resetBoard} />
      </div>

      <main className="grid gap-4 lg:grid-cols-2">
        <NaivePanel run={naive.state} elapsedMs={naiveClock} />
        <EngineeredPanel run={eng.state} elapsedMs={engClock} />
      </main>

      {!embed && (
        <footer className="mt-8 border-t border-line pt-4 text-xs text-mute">
          <p>
            Retrieval (BM25 + <span className="font-mono">bge-small</span> ONNX, fused with RRF), the semantic cache,
            Pydantic validation and the RAG-triad scoring always run for real. In <span className="text-warn">DEMO</span>{" "}
            mode only the LLM text is a deterministic simulation; with a Groq key it is live. Token counts are
            estimates priced at a flat $15 per million, with the 8B tier at 1/15 of the 70B price.
          </p>
        </footer>
      )}

      <KnowledgeDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} retrievedDocIds={retrievedDocIds} />
    </div>
  );
}
