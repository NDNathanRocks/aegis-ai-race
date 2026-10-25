"use client";

import { Fragment } from "react";
import { LENSES, OUTCOMES, RETRIEVAL_NAME, RETRIEVAL_PITCH, RETRIEVAL_TAGLINE, RETRIEVAL_TECH } from "@/lib/brand";

/** Business pitch for the retrieval layer: what it is, how it works in plain terms, what it changes for a company. */
export function ValuePitch() {
  return (
    <section aria-labelledby="pitch-title" className="mb-6 rounded-2xl border border-eng/30 bg-panel p-4 sm:p-5">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="min-w-0">
          <p className="num text-[11px] uppercase tracking-[0.2em] text-eng">The engine behind the right-hand side</p>
          <h2 id="pitch-title" className="mt-1 text-xl font-semibold tracking-tight">
            {RETRIEVAL_NAME}
          </h2>
          <p className="mt-1 text-sm font-medium text-ink">{RETRIEVAL_TAGLINE}</p>
          <p className="mt-2 text-sm text-mute">{RETRIEVAL_PITCH}</p>

          <div className="mt-4 grid gap-2 sm:grid-cols-[1fr_auto_1fr] sm:items-stretch">
            {LENSES.map((lens, i) => (
              <Fragment key={lens.name}>
                {i > 0 && (
                  <span aria-hidden className="self-center text-center font-mono text-sm text-eng">
                    +
                  </span>
                )}
                <LensCard {...lens} />
              </Fragment>
            ))}
          </div>
          <p className="mt-2 text-xs text-mute">
            <span className="text-eng">Fused ranking:</span> passages both lenses agree on rise to the top; the model
            sees only those, and a critic rejects any claim they do not support.
          </p>
          <p className="mt-2 font-mono text-[10px] text-mute">{RETRIEVAL_TECH}</p>
        </div>

        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-[0.2em] text-mute">What it means for your business</p>
          <ul className="mt-2 grid gap-2 sm:grid-cols-2">
            {OUTCOMES.map((o) => (
              <li key={o.title} className="rounded-lg border border-line bg-raised p-3">
                <h3 className="text-sm font-semibold text-ink">{o.title}</h3>
                <p className="mt-1 text-xs leading-relaxed text-mute">{o.body}</p>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-mute">
            Don&apos;t take our word for it: run a preset below. The left side is the same model without DualSight.
          </p>
        </div>
      </div>
    </section>
  );
}

function LensCard({ name, finds, examples }: { name: string; finds: string; examples: string }) {
  return (
    <div className="rounded-lg border border-line bg-bg/40 p-3">
      <p className="text-xs font-semibold text-eng">{name}</p>
      <p className="mt-1 text-xs text-ink">{finds}</p>
      <p className="mt-1 text-[11px] text-mute">{examples}</p>
    </div>
  );
}
