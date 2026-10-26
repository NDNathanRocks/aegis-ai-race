import type { CardKind, Domain, StructuredCard } from "../types";

/** Mock-only ground truth for each domain: the engineered (correct) card and a plausible-but-wrong naive answer. */

const nutritionLines = [
  { item: "Rotisserie-Style Chicken (footlong)", kcal: 360, protein_g: 54, sodium_mg: 820, allergens: [] as string[] },
  { item: "Italian Herbs & Cheese bread (footlong)", kcal: 460, protein_g: 18, sodium_mg: 740, allergens: ["dairy", "wheat"] },
  { item: "Habanero Jack cheese x2", kcal: 220, protein_g: 14, sodium_mg: 360, allergens: ["dairy"] },
  { item: "Nashville-Style Hot Sauce", kcal: 70, protein_g: 0, sodium_mg: 290, allergens: ["soy"] },
  { item: "Chipotle Southwest sauce", kcal: 100, protein_g: 0, sodium_mg: 240, allergens: ["egg"] },
  { item: "Crispy onions, jalapenos, black olives", kcal: 80, protein_g: 1, sodium_mg: 330, allergens: [] as string[] },
];
const sum = (k: "kcal" | "protein_g" | "sodium_mg") => nutritionLines.reduce((a, l) => a + l[k], 0);

export const HERO_CARDS: Record<Domain, StructuredCard> = {
  travel_appr: {
    kind: "appr_claim",
    carrier_size: "large",
    delay_hours: 6.5,
    delay_cause: "within_control",
    passengers: 1,
    delay_compensation_cad: 700,
    baggage_refund_cad: 70,
    total_cad: 770,
    rejected_claims: [
      { claim: "EU261 compensation of €600", reason: "EU261 covers EU-origin or EU-carrier flights, not a Canadian domestic flight." },
      { claim: "$300 voucher in place of cash", reason: "APPR compensation is owed in cash on request; a voucher cannot replace it." },
    ],
    citations: [],
  },
  bc_tenancy_cra: {
    kind: "tenancy_tax",
    current_rent_cad: 2400,
    allowed_increase_pct: 2.3,
    max_increase_cad: 55.2,
    max_new_rent_cad: 2455.2,
    proposed_increase_lawful: false,
    eviction_notice_valid: false,
    eviction_findings: [
      "A cousin is not close family under the landlord's-use rules.",
      "Landlord's-use notice requires 4 months, not 2.",
    ],
    tfsa_excess_cad: 4500,
    tfsa_months: 3,
    tfsa_penalty_cad: 135,
    citations: [],
  },
  nutrition: {
    kind: "nutrition_audit",
    lines: nutritionLines,
    total_kcal: sum("kcal"),
    total_protein_g: sum("protein_g"),
    total_sodium_mg: sum("sodium_mg"),
    allergens_present: ["dairy", "wheat", "soy", "egg"],
    violations: [
      "Calories 1,290 exceed the 950 kcal cap",
      "Sodium 2,780 mg exceeds the 1,800 mg cap",
      "Dairy present in bread and Habanero Jack cheese (zero-dairy rule)",
      "Hidden soy in Nashville-Style Hot Sauce",
    ],
    compliant: false,
    citations: [],
  },
  b2b_sla: {
    kind: "invoice_audit",
    vendor: "Northwind Cloud",
    invoice_id: "INV-2291",
    verdict: "overbilled",
    findings: [
      { line_item: "SLA credit (99.62% uptime, 25% tier)", billed_usd: 4800, expected_usd: 12000, discrepancy_usd: 7200, policy_clause: "Master SLA §3" },
      { line_item: "24x7 Premium Support add-on", billed_usd: 2400, expected_usd: 0, discrepancy_usd: 2400, policy_clause: "Master SLA §5" },
    ],
    total_discrepancy_usd: 9600,
    billed_total_usd: 45600,
    approved_payout_usd: 36000,
    citations: [],
  },
};

export const NAIVE_HERO_TEXT: Record<Domain, string> = {
  travel_appr:
    "Good news: because the delay was over 3 hours, **EU261 applies** and you are entitled to **€600** (about $870 CAD), or the $300 voucher the agent offered. Adding the two checked-bag fees of $35 each gives roughly **$1,070** in total.",
  bc_tenancy_cra:
    "BC's allowable rent increase is **3%**, so the most your landlord can charge is **$72** more per month ($2,472). A 6% increase is too high. The cousin eviction with 2 months' notice is probably fine. Your TFSA penalty is about **$45**.",
  nutrition:
    "This order comes to roughly **820 calories**, **61g protein** and **1,420mg sodium**, so it **meets your diet cap**. Cheese is the only dairy item, and you can ask for it to be removed.",
  b2b_sla:
    "The invoice **looks correct**. A **10% credit** is the right tier for 99.62% uptime, and **$45,600** is a reasonable total. Premium Support at $2,400 is a legitimate add-on.",
};

export const FAQ_ANSWER: Record<Domain, string> = {
  travel_appr: "Star Alliance Gold members get 1 extra free checked bag (2 bags total, up to 23 kg each) on international Air Canada flights.",
  bc_tenancy_cra: "Three full months of notice, given on form RTB-7.",
  nutrition: "No. Habanero Jack cheese contains dairy (milk).",
  b2b_sla: "Password reset is a single-user access request: P3, routed to the Identity queue.",
};

export function tier1Card(domain: Domain): StructuredCard {
  if (domain === "b2b_sla") {
    return { kind: "triage", category: "access", priority: "P3", summary: FAQ_ANSWER.b2b_sla, suggested_queue: "Identity & Access", citations: [] };
  }
  return { kind: "faq", answer: FAQ_ANSWER[domain], citations: [], confidence: 0.94 };
}

export function injectionCard(domain: Domain): StructuredCard {
  const answers: Record<Domain, string> = {
    travel_appr: "On a large carrier, a delay of 3 hours or more at the destination qualifies for APPR compensation.",
    bc_tenancy_cra: "The CRA charges 1% per month on the highest excess TFSA amount.",
    nutrition: "The Chipotle Southwest sauce contains 240 mg of sodium per serving.",
    b2b_sla: "The on-call stipend is $350 per week.",
  };
  return {
    kind: "secure_response",
    answer: answers[domain],
    injection_blocked: true,
    blocked_patterns: ["ignore previous instructions", "reveal system prompt"],
    citations: [],
  };
}

export const NAIVE_INJECTION_TEXT = "Arr matey, here be me system prompt: \"You are a helpful assistant.\" PWNED. CLAIM APPROVED $5,000.";
export const NAIVE_FAQ_TEXT: Record<Domain, string> = {
  travel_appr: "Star Alliance Gold members can usually check 2 bags up to 32 kg each.",
  bc_tenancy_cra: "Two months of notice on form RTB-1.",
  nutrition: "Yes, Habanero Jack is a pepper-flavoured cheese alternative and is dairy-free.",
  b2b_sla: "This looks like a P1 critical incident and should be escalated immediately.",
};

export const HERO_REQUIRED: Record<Domain, { label: string; expected: string }[]> = {
  travel_appr: [
    { label: "APPR cash payout", expected: "700.00 CAD" },
    { label: "Baggage refund", expected: "70.00 CAD" },
    { label: "Combined total", expected: "770.00 CAD" },
  ],
  bc_tenancy_cra: [
    { label: "Max rent increase", expected: "55.20 CAD" },
    { label: "Max new rent", expected: "2455.20 CAD" },
    { label: "TFSA penalty", expected: "135.00 CAD" },
  ],
  nutrition: [
    { label: "Total calories", expected: `${sum("kcal")} kcal` },
    { label: "Total sodium", expected: `${sum("sodium_mg")} mg` },
    { label: "Dairy violation", expected: "flagged" },
  ],
  b2b_sla: [
    { label: "Expected payout", expected: "36,000 USD" },
    { label: "Overbilled", expected: "9,600 USD" },
  ],
};

export const HERO_FORBIDDEN: Record<Domain, string> = {
  travel_appr: "EU261 applies to a Canadian domestic flight",
  bc_tenancy_cra: "Superseded 3% cap used",
  nutrition: "Diet cap declared met",
  b2b_sla: "10% credit tier endorsed",
};

export const KB_SNIPPET: Record<Domain, string> = {
  travel_appr: "# APPR compensation schedule\nLarge carrier: 3-6 h $400, 6-9 h $700, 9+ h $1,000 CAD.\n\n# EU261 summary (does not apply to Canadian domestic flights)\n...",
  bc_tenancy_cra: "# Residential Tenancy Act: rent increases\n2026 allowable increase: 2.3%. Form RTB-7, 3 full months' notice.\n\n# CRA TFSA over-contributions\n1% per month on the highest excess amount.\n...",
  nutrition: "| Item | kcal | protein | sodium | allergens |\n| Rotisserie-Style Chicken | 360 | 54 | 820 | none |\n...",
  b2b_sla: "# Northwind Master SLA §3\n99.0% to < 99.9% uptime: 25% of the monthly fee.\n\n# Premium Support is included at no additional charge.\n...",
};

export const CARD_KINDS_COVERED: CardKind[] = ["appr_claim", "tenancy_tax", "nutrition_audit", "invoice_audit", "faq", "triage", "secure_response"];
