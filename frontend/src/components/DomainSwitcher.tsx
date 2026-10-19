"use client";

import { useRef } from "react";
import { SHORT_LABEL } from "@/lib/domains";
import type { Domain, DomainInfo } from "@/lib/types";

export function DomainSwitcher({
  domains,
  active,
  disabled,
  onSelect,
}: {
  domains: DomainInfo[];
  active: Domain;
  disabled: boolean;
  onSelect: (d: Domain) => void;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: React.KeyboardEvent, i: number) => {
    const dir = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!dir || disabled) return;
    e.preventDefault();
    const n = (i + dir + domains.length) % domains.length;
    const next = domains[n];
    if (!next) return;
    refs.current[n]?.focus();
    onSelect(next.id);
  };
  return (
    <div role="tablist" aria-label="Knowledge domain" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {domains.map((d, i) => {
        const on = d.id === active;
        return (
          <button
            key={d.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            role="tab"
            id={`tab-${d.id}`}
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            disabled={disabled && !on}
            title={d.title}
            onClick={() => onSelect(d.id)}
            onKeyDown={(e) => onKey(e, i)}
            className={`flex min-h-[44px] items-center justify-center gap-2 rounded-lg border px-3 py-2 text-[13px] transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50 ${
              on ? "border-eng bg-raised text-ink" : "border-line bg-panel text-mute hover:border-line-strong hover:text-ink"
            }`}
          >
            <span aria-hidden>{d.emoji}</span>
            <span className="truncate font-medium">{SHORT_LABEL[d.id] ?? d.title}</span>
          </button>
        );
      })}
    </div>
  );
}
