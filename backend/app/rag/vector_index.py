"""Vector indexes: zero-config NumPy index (default) and pgvector (DATABASE_URL)."""
import hashlib
import logging
import time
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger("aegis.vector_index")


class VectorIndex(Protocol):
    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[int, float]]: ...


class LocalVectorIndex:
    """Brute-force cosine search. ~40 chunks, so exact search is fastest."""

    def __init__(self, vectors: np.ndarray):
        self.vectors = vectors

    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        sims = self.vectors @ query_vec
        order = np.argsort(-sims)[:k]
        return [(int(i), float(sims[i])) for i in order]

    @classmethod
    def build(cls, texts: list[str], embed, embedder_name: str, cache_dir: Path | None = None):
        """Embed `texts`, persisting vectors under cache_dir keyed by content hash."""
        key = hashlib.sha256((embedder_name + "\x00" + "\x00".join(texts)).encode()).hexdigest()[:16]
        path = cache_dir / f"index-{key}.npy" if cache_dir else None
        if path and path.exists():
            return cls(np.load(path))
        vecs = embed(texts)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, vecs)
        return cls(vecs)


class PgVectorIndex:
    """pgvector-backed index. Requires the `pgvector` extra and DATABASE_URL.

    Stores chunk vectors in `aegis_chunks(idx int primary key, embedding vector(dim))`
    and returns row indexes so it is a drop-in replacement for LocalVectorIndex.
    """

    def __init__(self, dsn: str, vectors: np.ndarray):
        import psycopg
        from pgvector.psycopg import register_vector

        self._dsn = dsn
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            register_vector(conn)
            conn.execute("DROP TABLE IF EXISTS aegis_chunks")
            conn.execute(
                f"CREATE TABLE aegis_chunks (idx int PRIMARY KEY, embedding vector({vectors.shape[1]}))"
            )
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO aegis_chunks (idx, embedding) VALUES (%s, %s)",
                    [(i, v) for i, v in enumerate(vectors)],
                )

    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        import psycopg
        from pgvector.psycopg import register_vector

        with psycopg.connect(self._dsn) as conn:
            register_vector(conn)
            rows = conn.execute(
                "SELECT idx, 1 - (embedding <=> %s) AS sim FROM aegis_chunks "
                "ORDER BY embedding <=> %s LIMIT %s",
                (query_vec, query_vec, k),
            ).fetchall()
        return [(int(i), float(s)) for i, s in rows]


def make_vector_index(settings, embedder, texts: list[str], attempts: int = 6, delay_s: float = 1.5) -> VectorIndex:
    """pgvector when DATABASE_URL is set and reachable, otherwise the local index.

    Postgres commonly starts a few seconds after the app in docker-compose, so connection
    failures are retried with a growing delay before falling back (loudly) to the local index."""
    local = LocalVectorIndex.build(texts, embedder.embed, embedder.name, settings.cache_dir)
    if not settings.database_url:
        return local
    for attempt in range(1, attempts + 1):
        try:
            return PgVectorIndex(settings.database_url, local.vectors)
        except Exception as e:
            if attempt == attempts:
                log.warning(
                    "pgvector unavailable after %d attempts (%s: %s); using the local vector index",
                    attempts, type(e).__name__, e,
                )
                break
            log.info("pgvector not ready (attempt %d/%d): %s", attempt, attempts, e)
            time.sleep(delay_s * attempt)
    return local
