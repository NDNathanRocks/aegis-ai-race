"use client";

import { useEffect, useRef, useState } from "react";
import { fetchDocument, fetchDocuments } from "@/lib/api";
import type { Domain, KbDocument, KbDocumentSummary } from "@/lib/types";
import { Badge } from "./ui";

function DocText({ text }: { text: string }) {
  return (
    <div className="space-y-1.5 text-[13px] leading-relaxed">
      {text.split("\n").map((line, i) => {
        if (line.startsWith("# ")) return <h3 key={i} className="pt-1 text-sm font-semibold">{line.slice(2)}</h3>;
        if (line.startsWith("## ")) return <h4 key={i} className="pt-2 text-xs font-semibold uppercase tracking-wider text-eng">{line.slice(3)}</h4>;
        if (!line.trim()) return null;
        return <p key={i} className="text-mute">{line}</p>;
      })}
    </div>
  );
}

export function KnowledgeDrawer({
  open,
  onClose,
  retrievedDocIds,
  domain,
}: {
  domain: Domain;
  open: boolean;
  onClose: () => void;
  retrievedDocIds: string[];
}) {
  const [docs, setDocs] = useState<KbDocumentSummary[] | null>(null);
  const [selected, setSelected] = useState<KbDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // Documents are domain-scoped: reset when the domain changes.
    setDocs(null);
    setSelected(null);
    setError(null);
  }, [domain]);

  useEffect(() => {
    if (!open || docs) return;
    const ctl = new AbortController();
    fetchDocuments(domain, ctl.signal)
      .then(setDocs)
      .catch((e: unknown) => {
        if (!ctl.signal.aborted) setError(e instanceof Error ? e.message : "Failed to load documents");
      });
    return () => ctl.abort();
  }, [open, docs, domain]);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const select = (id: string) => {
    setError(null);
    fetchDocument(domain, id)
      .then(setSelected)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load document"));
  };

  return (
    <>
      {open && <div className="fixed inset-0 z-30 bg-black/50" onClick={onClose} aria-hidden />}
      <aside
        id="kb-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Ground-truth knowledge base"
        aria-hidden={!open}
        inert={!open}
        className={`fixed inset-y-0 right-0 z-40 flex w-full max-w-xl flex-col border-l border-line bg-panel transition-transform duration-150 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold">Ground-Truth Knowledge Base</h2>
            <p className="text-[11px] text-mute">The corpus both sides are judged against</p>
          </div>
          <button ref={closeRef} onClick={onClose} aria-label="Close knowledge base" className="min-h-[44px] min-w-[44px] rounded text-mute hover:text-ink">
            ✕
          </button>
        </header>
        <div className="grid min-h-0 flex-1 grid-rows-[auto_1fr] sm:grid-cols-[13rem_1fr] sm:grid-rows-1">
          <nav aria-label="Documents" className="scroll-thin overflow-auto border-b border-line p-2 sm:border-b-0 sm:border-r">
            {!docs && !error && <p className="p-2 text-xs text-mute">Loading…</p>}
            {docs?.map((d) => (
              <button
                key={d.id}
                onClick={() => select(d.id)}
                className={`mb-1 w-full rounded-lg px-2.5 py-2 text-left text-xs transition-colors hover:bg-raised ${
                  selected?.id === d.id ? "bg-raised" : ""
                }`}
              >
                <div className="font-medium leading-snug">{d.title}</div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-mute">
                  {d.category}
                  {retrievedDocIds.includes(d.id) && <Badge tone="eng">retrieved</Badge>}
                </div>
              </button>
            ))}
          </nav>
          <div className="scroll-thin min-h-0 overflow-auto p-4">
            {error && <p role="alert" className="text-xs text-bad">{error}</p>}
            {selected ? <DocText text={selected.text} /> : !error && <p className="text-xs text-mute">Select a document to read its full text.</p>}
          </div>
        </div>
      </aside>
    </>
  );
}
