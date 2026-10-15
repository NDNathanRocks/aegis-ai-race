"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { ApiError, streamRace } from "./sse";
import type { Action, RunStatus } from "./reducer";
import type { RaceEvent, RaceRequest, Side } from "./types";

interface Hook<S> {
  state: S;
  start: (req: RaceRequest) => Promise<void>;
  abort: () => void;
}

/** Drives one side of the race: streams SSE events from the backend into a reducer. */
export function useRace<S extends { status: RunStatus }>(
  side: Side,
  reducer: (s: S, a: Action) => S,
  init: () => S,
): Hook<S> {
  const [state, dispatch] = useReducer(reducer, undefined, init);
  const controller = useRef<AbortController | null>(null);

  const abort = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
  }, []);

  useEffect(() => abort, [abort]);

  const start = useCallback(
    async (req: RaceRequest) => {
      abort();
      const ctl = new AbortController();
      controller.current = ctl;
      dispatch({ type: "start" });
      let terminated = false;
      const onEvent = (event: RaceEvent) => {
        if (ctl.signal.aborted) return;
        if (event.event === "done" || event.event === "error") terminated = true;
        dispatch({ type: "event", event });
      };
      try {
        await streamRace(side, req, onEvent, ctl.signal);
        if (!terminated && !ctl.signal.aborted) {
          dispatch({ type: "fail", message: "The stream ended unexpectedly." });
        }
      } catch (err) {
        if (ctl.signal.aborted) return;
        dispatch({
          type: "fail",
          message: err instanceof ApiError ? err.message : "Connection lost while streaming.",
        });
      }
    },
    [abort, side],
  );

  return { state, start, abort };
}

/** Live elapsed-time readout: ticks while running, then snaps to the server's authoritative total. */
export function useRunClock(status: RunStatus, totalMs: number | null): number | null {
  const startedAt = useRef<number>(0);
  const [elapsed, setElapsed] = useState<number | null>(null);

  useEffect(() => {
    if (status === "idle") {
      setElapsed(null);
      return;
    }
    if (status !== "running") return;
    startedAt.current = performance.now();
    setElapsed(0);
    const id = window.setInterval(() => setElapsed(performance.now() - startedAt.current), 50);
    return () => window.clearInterval(id);
  }, [status]);

  if (status === "done" && totalMs !== null) return totalMs;
  return elapsed;
}
