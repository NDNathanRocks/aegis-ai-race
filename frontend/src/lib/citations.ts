/** What a click on a citation hands up: the document to open and the passage (possibly empty) to highlight. */
export interface CitationTarget {
  docId: string;
  section: string;
  text: string;
}

/** The citation the drawer is showing. */
export interface CitationFocus extends CitationTarget {
  /** Changes on every click so re-clicking the same citation scrolls to it again. */
  nonce: number;
}

/**
 * Indices of the document lines that belong to a retrieved passage. Chunk bodies are copied line-for-line from the
 * source document (see backend `chunk_document`), so an exact trimmed-line match is reliable; the section headings
 * named in the chunk label are included so the highlight starts at the right heading.
 */
export function passageLineIndices(docText: string, chunkText: string, section: string): Set<number> {
  const body = new Set(
    chunkText
      .split("\n")
      .slice(1) // first line is the "Doc title — section" label added by the chunker
      .map((l) => l.trim())
      .filter((l) => l.length > 0),
  );
  const headings = new Set(
    section
      .split("; ")
      .map((s) => s.replace(/ \(cont\.\)$/, "").trim())
      .filter(Boolean),
  );
  const hits = new Set<number>();
  docText.split("\n").forEach((line, i) => {
    const t = line.trim();
    if (!t) return;
    if (body.has(t) || (t.startsWith("## ") && headings.has(t.slice(3).trim()))) hits.add(i);
  });
  return hits;
}
