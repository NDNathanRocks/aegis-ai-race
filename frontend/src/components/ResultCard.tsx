import type { RetrievedChunk, StructuredCard } from "@/lib/types";
import { money } from "@/lib/format";
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
