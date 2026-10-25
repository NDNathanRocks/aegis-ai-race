"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface TourCaption {
  title: string;
  body: string;
}

export interface TourView extends TourCaption {
  index: number;
  total: number;
}

/** Handed to a tour script: show a caption, wait (honouring pause / next / exit), and check it is still running. */
export interface TourApi {
  show: (index: number, total: number, caption: TourCaption) => void;
  /** Resolves true after `ms` of unpaused time or a "next" click; false once the tour has been exited. */
  wait: (ms: number) => Promise<boolean>;
  alive: () => boolean;
}

const TICK_MS = 100;

/** Drives a scripted, interruptible walkthrough. Starting a new tour or exiting invalidates the running script. */
export function useTour() {
  const [view, setView] = useState<TourView | null>(null);
  const [paused, setPaused] = useState(false);
  const token = useRef(0);
  const pausedRef = useRef(false);
  const skipRef = useRef(false);

  const exit = useCallback(() => {
    token.current += 1;
    pausedRef.current = false;
    setPaused(false);
    setView(null);
  }, []);

  useEffect(() => exit, [exit]);

  const togglePause = useCallback(() => {
    pausedRef.current = !pausedRef.current;
    setPaused(pausedRef.current);
  }, []);

  const next = useCallback(() => {
    skipRef.current = true;
  }, []);

  const start = useCallback(async (script: (t: TourApi) => Promise<void>) => {
    const mine = ++token.current;
    pausedRef.current = false;
    skipRef.current = false;
    setPaused(false);
    const alive = () => token.current === mine;
    const api: TourApi = {
      alive,
      show: (index, total, caption) => {
        if (!alive()) return;
        skipRef.current = false;
        setView({ index, total, ...caption });
      },
      wait: async (ms) => {
        let left = ms;
        while (alive() && left > 0 && !skipRef.current) {
          await new Promise((r) => setTimeout(r, TICK_MS));
          if (!pausedRef.current) left -= TICK_MS;
        }
        skipRef.current = false;
        return alive();
      },
    };
    await script(api); // the last caption stays up until the viewer presses Finish
  }, []);

  return { view, paused, start, exit, next, togglePause, active: view !== null };
}
