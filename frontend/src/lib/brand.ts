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
    title: "Lower AI spend",
    body: "Only the relevant passages are sent to the model, not the whole knowledge base, so each question uses a fraction of the tokens. Watch the token counter on both sides.",
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
