"use client";

import { useEffect, type RefObject } from "react";

/** Message a host page listens for to size its <iframe>. */
export const RESIZE_MESSAGE = "aegis:resize";

/**
 * Re-posts the content height to the parent window whenever it can have changed: a ResizeObserver on the root
 * element (not just window resize), plus CSS transition/animation end events bubbling from drawers, banners and
 * cards, plus a re-post whenever `deps` change (after layout settles). No-op outside an iframe / outside embed mode.
 */
export function useEmbedResize(rootRef: RefObject<HTMLElement | null>, embed: boolean, deps: readonly unknown[]): void {
  useEffect(() => {
    const root = rootRef.current;
    if (!embed || !root || window.parent === window) return;
    let last = -1;
    const post = (force: boolean) => {
      const height = Math.ceil(root.getBoundingClientRect().height);
      if (!force && height === last) return;
      last = height;
      window.parent.postMessage({ type: RESIZE_MESSAGE, height }, "*");
    };
    const ro = new ResizeObserver(() => post(false));
    ro.observe(root);
    const onEnd = () => post(true);
    root.addEventListener("transitionend", onEnd);
    root.addEventListener("animationend", onEnd);
    window.addEventListener("resize", onEnd);
    post(true);
    return () => {
      ro.disconnect();
      root.removeEventListener("transitionend", onEnd);
      root.removeEventListener("animationend", onEnd);
      window.removeEventListener("resize", onEnd);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [embed, rootRef]);

  // State changes that open/close drawers, banners or cards: post once layout has committed and again after the 150ms transition.
  useEffect(() => {
    const root = rootRef.current;
    if (!embed || !root || window.parent === window) return;
    const post = () =>
      window.parent.postMessage({ type: RESIZE_MESSAGE, height: Math.ceil(root.getBoundingClientRect().height) }, "*");
    const raf = window.requestAnimationFrame(post);
    const timer = window.setTimeout(post, 200);
    return () => {
      window.cancelAnimationFrame(raf);
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [embed, rootRef, ...deps]);
}
