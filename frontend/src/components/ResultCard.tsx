import type { RetrievedChunk, StructuredCard } from "@/lib/types";
import { cad, money } from "@/lib/format";
import { Badge } from "./ui";

function Citations({ ids, chunks }: { ids: string[]; chunks: RetrievedChunk[] }) {
  if (!ids.length) return null;
  const byId = new Map(chunks.map((c) => [c.chunk_id, c]));
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line pt-2.5">
      <span className="text-[10px] uppercase tracking-wider text-mute">Sources</span>
      {ids.map((id) => {
        const c = byId.get(id);
        return (
          <Badge key={id} tone="eng" title={c?.text ?? id}>
            {c ? `${c.doc_title} § ${c.section}` : id}
          </Badge>
        );
      })}
    </div>
  );
}

function Row({ label, value, tone, strong }: { label: string; value: string; tone?: "bad" | "good"; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-line py-1.5 first:border-t-0">
      <span className="text-xs text-mute">{label}</span>
      <span className={`num text-right text-xs ${strong ? "text-sm font-semibold" : ""} ${tone === "bad" ? "text-bad" : tone === "good" ? "text-good" : "text-ink"}`}>
        {value}
      </span>
    </div>
  );
}

const PRIORITY_TONE = { P1: "bad", P2: "warn", P3: "eng", P4: "neutral" } as const;

export function ResultCard({ card, chunks }: { card: StructuredCard; chunks: RetrievedChunk[] }) {
  switch (card.kind) {
    case "invoice_audit": {
      const tone = card.verdict === "compliant" ? "good" : card.verdict === "needs_review" ? "warn" : "bad";
      return (
        <div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold">
                {card.vendor} · <span className="font-mono">{card.invoice_id}</span>
              </div>
              <div className="text-[11px] text-mute">Invoice audit against SLA &amp; AP policy</div>
            </div>
            <Badge tone={tone} className="uppercase">
              {card.verdict}
            </Badge>
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[420px] text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-mute">
                <tr>
                  <th className="pb-1 pr-2 font-medium">Finding</th>
                  <th className="pb-1 pr-2 text-right font-medium">Billed</th>
                  <th className="pb-1 pr-2 text-right font-medium">Expected</th>
                  <th className="pb-1 text-right font-medium">Δ</th>
                </tr>
              </thead>
              <tbody>
                {card.findings.map((f) => (
                  <tr key={f.line_item} className="border-t border-line align-top">
                    <td className="py-1.5 pr-2">
                      {f.line_item}
                      <div className="font-mono text-[10px] text-mute">{f.policy_clause}</div>
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono tabular-nums">{money(f.billed_usd)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono tabular-nums">{money(f.expected_usd)}</td>
                    <td className="py-1.5 text-right font-mono tabular-nums text-bad">{money(f.discrepancy_usd)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-line">
                  <td colSpan={3} className="pt-2 text-right text-[11px] text-mute">
                    Total discrepancy (sum of findings)
                  </td>
                  <td className="pt-2 text-right font-mono text-sm font-semibold tabular-nums text-bad">
                    {money(card.total_discrepancy_usd)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
          <Citations ids={card.citations} chunks={chunks} />
        </div>
      );
    }
    case "triage":
      return (
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="eng" className="uppercase">
              {card.category}
            </Badge>
            <Badge tone={PRIORITY_TONE[card.priority]}>{card.priority}</Badge>
            <Badge>→ {card.suggested_queue}</Badge>
          </div>
          <p className="mt-3 text-sm">{card.summary}</p>
          <Citations ids={card.citations} chunks={chunks} />
        </div>
      );
    case "secure_response":
      return (
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={card.injection_blocked ? "good" : "neutral"}>
              {card.injection_blocked ? "🛡 Injection blocked" : "No injection detected"}
            </Badge>
            {card.blocked_patterns.map((p) => (
              <Badge key={p} tone="warn">
                {p}
              </Badge>
            ))}
          </div>
          <p className="mt-3 text-sm">{card.answer}</p>
          <Citations ids={card.citations} chunks={chunks} />
        </div>
      );
    case "appr_claim":
      return (
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="eng" className="uppercase">APPR · {card.carrier_size} carrier</Badge>
            <Badge>{card.delay_cause.replace(/_/g, " ")}</Badge>
            <Badge>
              <span className="num">{card.delay_hours}</span> h · {card.passengers} pax
            </Badge>
          </div>
          <div className="mt-3">
            <Row label="Delay compensation (cash)" value={cad(card.delay_compensation_cad)} />
            <Row label="Baggage fee refund" value={cad(card.baggage_refund_cad)} />
            <Row label="Total owed" value={cad(card.total_cad)} strong tone="good" />
          </div>
          {card.rejected_claims.length > 0 && (
            <div className="mt-3">
              <div className="mb-1 text-[10px] uppercase tracking-wider text-mute">Rejected claims</div>
              <ul className="space-y-1.5 text-xs">
                {card.rejected_claims.map((r) => (
                  <li key={r.claim} className="rounded border border-line bg-bg/40 px-2.5 py-1.5">
                    <span className="text-bad">✕ {r.claim}</span>
                    <div className="text-[11px] text-mute">{r.reason}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <Citations ids={card.citations} chunks={chunks} />
        </div>
      );
    case "tenancy_tax":
      return (
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={card.proposed_increase_lawful ? "good" : "bad"}>
              6% increase {card.proposed_increase_lawful ? "lawful" : "unlawful"}
            </Badge>
            <Badge tone={card.eviction_notice_valid ? "good" : "bad"}>
              eviction notice {card.eviction_notice_valid ? "valid" : "invalid"}
            </Badge>
          </div>
          <div className="mt-3">
            <Row label="Current rent" value={cad(card.current_rent_cad)} />
            <Row label={`Allowed increase (${card.allowed_increase_pct}%)`} value={cad(card.max_increase_cad)} />
            <Row label="Max new rent" value={cad(card.max_new_rent_cad)} />
            <Row label={`TFSA excess ${cad(card.tfsa_excess_cad)} x ${card.tfsa_months} mo`} value={cad(card.tfsa_penalty_cad)} strong tone="bad" />
          </div>
          {card.eviction_findings.length > 0 && (
            <ul className="mt-3 space-y-1 text-[11px] text-mute">
              {card.eviction_findings.map((f) => (
                <li key={f} className="flex gap-1.5">
                  <span aria-hidden className="text-bad">✕</span>
                  {f}
                </li>
              ))}
            </ul>
          )}
          <Citations ids={card.citations} chunks={chunks} />
        </div>
      );
    case "nutrition_audit":
      return (
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={card.compliant ? "good" : "bad"} className="uppercase">
              {card.compliant ? "within diet" : "violations found"}
            </Badge>
            {card.allergens_present.map((a) => (
              <Badge key={a} tone="warn">{a}</Badge>
            ))}
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[360px] text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-mute">
                <tr>
                  <th className="pb-1 pr-2 font-medium">Item</th>
                  <th className="pb-1 pr-2 text-right font-medium">kcal</th>
                  <th className="pb-1 pr-2 text-right font-medium">Protein</th>
                  <th className="pb-1 text-right font-medium">Sodium</th>
                </tr>
              </thead>
              <tbody>
                {card.lines.map((l) => (
                  <tr key={l.item} className="border-t border-line align-top">
                    <td className="py-1.5 pr-2">
                      {l.item}
                      {l.allergens.length > 0 && <div className="text-[10px] text-warn">{l.allergens.join(", ")}</div>}
                    </td>
                    <td className="num py-1.5 pr-2 text-right">{l.kcal}</td>
                    <td className="num py-1.5 pr-2 text-right">{l.protein_g} g</td>
                    <td className="num py-1.5 text-right">{l.sodium_mg} mg</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-line-strong text-sm font-semibold">
                  <td className="pt-2 text-[11px] font-normal text-mute">Totals</td>
                  <td className="num pt-2 pr-2 text-right">{card.total_kcal}</td>
                  <td className="num pt-2 pr-2 text-right">{card.total_protein_g} g</td>
                  <td className="num pt-2 text-right">{card.total_sodium_mg} mg</td>
                </tr>
              </tfoot>
            </table>
          </div>
          {card.violations.length > 0 && (
            <ul className="mt-3 space-y-1 text-[11px] text-bad">
              {card.violations.map((v) => (
                <li key={v}>✕ {v}</li>
              ))}
            </ul>
          )}
          <Citations ids={card.citations} chunks={chunks} />
        </div>
      );
    case "faq":
      return (
        <div>
          <p className="text-sm">{card.answer}</p>
          <div className="mt-2 text-[11px] text-mute">
            Model confidence <span className="font-mono text-ink">{Math.round(card.confidence * 100)}%</span>
          </div>
          <Citations ids={card.citations} chunks={chunks} />
        </div>
      );
  }
}
