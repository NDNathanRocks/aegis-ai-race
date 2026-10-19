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
    source_note: str = ""
    atomic: bool = False  # keep the whole document as ONE chunk (data tables that must not be split)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    section: str
    text: str


DEFAULT_DOMAIN = "b2b_sla"


def domain_dirs(corpus_root: Path) -> list[Path]:
    """Domain sub-directories (those holding a manifest.json), sorted by name."""
    return sorted(p for p in corpus_root.iterdir() if p.is_dir() and (p / "manifest.json").exists())


def _resolve(corpus_dir: Path) -> Path:
    """A domain dir is used as is. The corpus ROOT (pre-v2 callers) resolves to the default B2B domain."""
    if (corpus_dir / "manifest.json").exists():
        return corpus_dir
    legacy = corpus_dir / DEFAULT_DOMAIN
    return legacy if (legacy / "manifest.json").exists() else corpus_dir


def load_documents(corpus_dir: Path) -> list[Document]:
    """Documents of ONE domain directory (`data/corpus/<domain>`)."""
    corpus_dir = _resolve(corpus_dir)
    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    docs = []
    for entry in manifest["documents"]:
        text = (corpus_dir / f"{entry['id']}.md").read_text(encoding="utf-8")
        docs.append(
            Document(entry["id"], entry["title"], entry["category"], text, entry.get("source_note", ""), bool(entry.get("atomic", False)))
        )
    return docs


def corpus_version(corpus_dir: Path) -> str:
    """Stable hash of the corpus content; namespaces cache entries.

    Given a domain dir it hashes that domain; given the corpus root it hashes every domain."""
    h = hashlib.sha256()
    dirs = [corpus_dir] if (corpus_dir / "manifest.json").exists() else domain_dirs(corpus_dir)
    for d in dirs:
        if len(dirs) > 1:
            h.update(d.name.encode())
        for doc in load_documents(d):
            h.update(doc.id.encode())
            h.update(doc.text.encode())
    return h.hexdigest()[:12]


_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")


def chunk_document(doc: Document, max_words: int = 180, pack: bool = True) -> list[Chunk]:
    """Split by `##` sections (long ones on line boundaries), then pack neighbouring small sections together.

    The document title is prefixed to every chunk so lexical and dense search
    both see which document a clause belongs to.
    """
    if doc.atomic:
        lines = [ln.strip() for ln in doc.text.splitlines() if ln.strip() and not ln.startswith("# ")]
        body = "\n".join(lines)
        return [Chunk(f"{doc.id}#0", doc.id, doc.title, "Complete table", f"{doc.title}\n{body}")]
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

    # 1) split long sections on line boundaries -> (section label, body, words)
    pieces: list[tuple[str, str, int]] = []
    for section, lines in sections:
        buf: list[str] = []
        words = 0
        parts: list[tuple[str, int]] = []
        for line in lines:
            n = len(line.split())
            if buf and words + n > max_words:
                parts.append(("\n".join(buf), words))
                buf, words = [], 0
            buf.append(line)
            words += n
        if buf:
            parts.append(("\n".join(buf), words))
        for i, (body, w) in enumerate(parts):
            pieces.append((section if i == 0 else f"{section} (cont.)", body, w))

    # 2) pack consecutive small sections of the same document into one chunk (up to max_words), so a
    #    multi-topic question needs fewer chunks to cover its facts and tiny fragments do not crowd the top-k.
    packed: list[list] = []
    for section, body, w in pieces:
        if pack and packed and packed[-1][2] + w <= max_words:
            packed[-1][0].append(section)
            packed[-1][1].append(f"{section}:\n{body}")
            packed[-1][2] += w
        else:
            packed.append([[section], [body], w])

    chunks: list[Chunk] = []
    for sections_, bodies, _ in packed:
        idx = len(chunks)
        label = "; ".join(sections_)
        chunks.append(
            Chunk(
                chunk_id=f"{doc.id}#{idx}",
                doc_id=doc.id,
                doc_title=doc.title,
                section=label,
                text=f"{doc.title} — {label}\n" + "\n".join(bodies),
            )
        )
    return chunks


def load_chunks(corpus_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in load_documents(corpus_dir):
        chunks.extend(chunk_document(doc))
    return chunks
