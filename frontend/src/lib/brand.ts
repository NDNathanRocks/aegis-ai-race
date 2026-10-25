/** Business-facing naming and copy for the retrieval layer. One place to rename or reword it. */

export const RETRIEVAL_NAME = "DualSight Retrieval";
export const RETRIEVAL_TECH = "Hybrid RAG · BM25 keyword + dense vector search, fused with Reciprocal Rank Fusion";
export const RETRIEVAL_TAGLINE = "Finds the exact clause and the right meaning, then makes the AI answer from it.";

export const RETRIEVAL_PITCH =
  "Most AI assistants guess from memory or skim a pile of documents. DualSight reads your knowledge base through " +
  "two lenses at once and hands the model only the passages that matter, so every answer is grounded in your own " +
  "policies, contracts and price sheets, with the source attached.";

export interface Lens {
  name: string;
  finds: string;
  examples: string;
}

export const LENSES: Lens[] = [
  {
    name: "Exact lens",
    finds: "Matches the precise words and numbers people use.",
    examples: "Invoice IDs, clause numbers, SKUs, dollar amounts, product names",
  },
  {
    name: "Meaning lens",
    finds: "Understands what is being asked, however it is phrased.",
    examples: "“Can they kick me out to move in?” finds “landlord's use of property”",
  },
];

export interface Outcome {
  title: string;
  body: string;
}

export const OUTCOMES: Outcome[] = [
  {
    title: "Answers you can audit",
    body: "Every answer cites the passages it came from. Compliance, finance and support can check the source in one click instead of trusting a black box.",
  },
  {
    title: "Fewer costly mistakes",
    body: "Keyword search alone misses paraphrases; AI search alone blurs exact figures. Using both is what catches the overbilled invoice or the superseded rate.",
  },
  {
    title: "Pay for right answers",
    body: "A cheap wrong answer is the most expensive kind. Sending only the relevant passages usually cuts input tokens; on hard questions it may spend more to get it right. The scoreboard tracks cost per correct answer.",
  },
  {
    title: "Live on your documents",
    body: "No model training and no fine-tuning. Point it at the policies you already have; update a document and the next answer reflects it.",
  },
];

/** Which lens(es) ranked a retrieved passage. `null` score = that search did not surface it. */
export function lensOf(dense: number | null, bm25: number | null): "both" | "exact" | "meaning" {
  if (dense !== null && bm25 !== null) return "both";
  return bm25 !== null ? "exact" : "meaning";
}

/** Pitch mode (`?tour=1` or the header button): one caption per step of the scripted walkthrough. */
export const TOUR = {
  intro: {
    title: `Meet ${RETRIEVAL_NAME}`,
    body: "Two AIs, same model, same documents. The left is a typical AI wrapper; the right adds DualSight and a production pipeline. Watch what changes.",
  },
  trap: {
    title: "The hallucination trap",
    body: "A tricky question goes to both sides. The left reads the whole knowledge base at once; the right pulls the exact clauses, then a critic checks every figure.",
  },
  verdict: {
    title: "The verdict",
    body: "Both answers are checked against an answer key in code, not by another AI. Click a source on the right to see the passage behind the answer.",
  },
  cache: {
    title: "Asked again, in different words",
    body: "The semantic cache recognises the same question and answers in milliseconds for $0. The left side pays full price again.",
  },
  injection: {
    title: "An attack hidden in the question",
    body: "This prompt tells the AI to ignore its rules. The left obeys; the right strips the attack and still returns a strictly formatted answer.",
  },
  end: {
    title: "What you just saw",
    body: "Answers grounded in your own documents, checked before they ship, near-free on repeat questions and resistant to manipulation. The scoreboard shows cost per correct answer.",
  },
} as const;
