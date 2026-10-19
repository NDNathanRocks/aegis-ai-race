"""Bake per-domain chunk vectors into the image cache at build time.

    python -m app.rag.prebuild [--cache-dir DIR]

Run during `docker build` (after the embedding model is baked) so a cold container never embeds the corpus at
runtime: LocalVectorIndex.build finds `index-<hash>.npy` for every domain and just loads it. The hash covers the
embedder name and the exact chunk texts, so a changed corpus simply misses the cache and is rebuilt on boot."""
import argparse
import time
from pathlib import Path

from app.config import Settings
from app.rag.corpus import load_chunks
from app.rag.embeddings import get_embedder
from app.rag.vector_index import LocalVectorIndex


def prebuild(settings: Settings, cache_dir: Path | None = None) -> dict[str, dict]:
    from app.domains import DOMAIN_ORDER

    cache_dir = cache_dir or settings.cache_dir
    embedder = get_embedder(settings.embedding_backend, settings.embedding_model)
    out: dict[str, dict] = {}
    for did in DOMAIN_ORDER:
        t0 = time.perf_counter()
        chunks = load_chunks(Path(settings.corpus_dir) / did)
        LocalVectorIndex.build([c.text for c in chunks], embedder.embed, embedder.name, cache_dir)
        out[did] = {"chunks": len(chunks), "ms": round((time.perf_counter() - t0) * 1000)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", type=Path, default=None)
    args = ap.parse_args()
    settings = Settings()
    stats = prebuild(settings, args.cache_dir)
    for did, s in stats.items():
        print(f"{did}: {s['chunks']} chunks, {s['ms']} ms")
    print(f"index cache: {args.cache_dir or settings.cache_dir}")


if __name__ == "__main__":
    main()
