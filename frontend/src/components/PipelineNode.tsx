"use client";

import { motion, useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";
import type { NodeStatus } from "@/lib/reducer";
import { fmtMs } from "@/lib/format";
import { Badge, StatusDot } from "./ui";

// Literal colours (framer-motion cannot animate CSS-variable colours). Mirrors the tokens in globals.css.
const BORDER: Record<NodeStatus, string> = {
  idle: "rgb(30, 34, 48)",
  active: "rgb(212, 167, 44)",
  done: "rgba(91, 197, 167, 0.55)",
  skipped: "rgb(30, 34, 48)",
  error: "rgba(229, 72, 77, 0.7)",
};

export function PipelineNode({
  index,
  title,
  subtitle,
  status,
  latencyMs,
  badges,
  children,
  last = false,
}: {
  index: number;
  title: string;
  subtitle: string;
  status: NodeStatus;
  latencyMs: number | null;
  badges?: ReactNode;
  children?: ReactNode;
  last?: boolean;
}) {
  const reduce = useReducedMotion();
  const lit = status !== "idle";
  return (
    <li className="relative pl-9" aria-label={`${title}: ${status}`}>
      {!last && (
        <span aria-hidden className="absolute left-[13px] top-8 h-[calc(100%-1rem)] w-px bg-line">
          <motion.span
            className="absolute inset-x-0 top-0 block bg-eng"
            initial={false}
            animate={{ height: status === "done" || status === "skipped" ? "100%" : "0%" }}
            transition={{ duration: reduce ? 0 : 0.18 }}
          />
        </span>
      )}
      <motion.span
        aria-hidden
        className="absolute left-0 top-1 flex h-7 w-7 items-center justify-center rounded-full border bg-panel font-mono text-xs"
        initial={false}
        animate={{
          borderColor: BORDER[status],
        }}
        transition={{ duration: reduce ? 0 : 0.15 }}
      >
        {status === "done" ? <span className="text-eng">✓</span> : status === "error" ? <span className="text-bad">!</span> : index}
      </motion.span>

      <motion.div
        initial={false}
        animate={{ opacity: lit ? 1 : 0.55, borderColor: BORDER[status] }}
        transition={{ duration: reduce ? 0 : 0.15 }}
        className="mb-3 rounded-xl border bg-raised"
      >
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[13px] font-semibold">
              <StatusDot status={status} />
              <span className="truncate">{title}</span>
            </div>
            <div className="text-[11px] text-mute">{subtitle}</div>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            {badges}
            {status === "skipped" && <Badge>skipped</Badge>}
            {latencyMs !== null && status !== "skipped" && (
              <Badge tone="eng" title="Server-side latency of this step">
                {fmtMs(latencyMs)}
              </Badge>
            )}
          </div>
        </div>
        {children && lit && status !== "skipped" && <div className="border-t border-line px-3 py-3">{children}</div>}
      </motion.div>
    </li>
  );
}
