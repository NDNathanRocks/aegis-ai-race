"""Load the markdown corpus and split it into heading-aware chunks."""
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    category: str
    text: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    section: str
    text: str


def load_documents(corpus_dir: Path) -> list[Document]:
    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    docs = []
    for entry in manifest["documents"]:
        text = (corpus_dir / f"{entry['id']}.md").read_text(encoding="utf-8")
        docs.append(Document(entry["id"], entry["title"], entry["category"], text))
    return docs


def corpus_version(corpus_dir: Path) -> str:
    """Stable hash of the corpus content; namespaces cache entries."""
    h = hashlib.sha256()
    for doc in load_documents(corpus_dir):
        h.update(doc.id.encode())
        h.update(doc.text.encode())
    return h.hexdigest()[:12]


_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")


def chunk_document(doc: Document, max_words: int = 140) -> list[Chunk]:
    """Split by `##` sections; long sections are split on line boundaries.

    The document title is prefixed to every chunk so lexical and dense search
    both see which document a clause belongs to.
    """
    sections: list[tuple[str, list[str]]] = []
    current_title, current_lines = "Overview", []
    for line in doc.text.splitlines():
        m = _HEADING.match(line)
        if m and len(m.group(1)) >= 2:
            if current_lines:
                sections.append((current_title, current_lines))
            current_title, current_lines = m.group(2).strip(), []
        elif m:  # H1 = document title, not a section
            continue
        elif line.strip():
            current_lines.append(line.strip())
    if current_lines:
        sections.append((current_title, current_lines))

    chunks: list[Chunk] = []
    for section, lines in sections:
        buf: list[str] = []
        words = 0
        parts: list[str] = []
        for line in lines:
            n = len(line.split())
            if buf and words + n > max_words:
                parts.append("\n".join(buf))
                buf, words = [], 0
            buf.append(line)
            words += n
        if buf:
            parts.append("\n".join(buf))
        for i, body in enumerate(parts):
            idx = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.id}#{idx}",
                    doc_id=doc.id,
                    doc_title=doc.title,
                    section=section if i == 0 else f"{section} (cont.)",
                    text=f"{doc.title} — {section}\n{body}",
                )
            )
    return chunks


def load_chunks(corpus_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in load_documents(corpus_dir):
        chunks.extend(chunk_document(doc))
    return chunks
