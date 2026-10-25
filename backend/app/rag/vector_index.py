"""Vector indexes: zero-config NumPy index (default) and pgvector (DATABASE_URL)."""
import hashlib
import logging
import re
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

    Stores chunk vectors in `aegis_chunks[_<namespace>](idx int primary key, embedding vector(dim))`
    and returns row indexes so it is a drop-in replacement for LocalVectorIndex.
    """

    def __init__(self, dsn: str, vectors: np.ndarray, namespace: str = ""):
        import psycopg
        from pgvector.psycopg import register_vector
        from psycopg import sql

        if namespace and not re.fullmatch(r"[a-z0-9_]{1,40}", namespace):
            raise ValueError("invalid vector index namespace")
        # One table per domain: each domain's index is rebuilt independently at startup.
        self._table = "aegis_chunks" + (f"_{namespace}" if namespace else "")
        self._dsn = dsn
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            register_vector(conn)
            table = sql.Identifier(self._table)
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
            conn.execute(
                sql.SQL("CREATE TABLE {} (idx int PRIMARY KEY, embedding vector({}))").format(
                    table, sql.Literal(int(vectors.shape[1]))
                )
            )
            with conn.cursor() as cur:
                cur.executemany(
                    sql.SQL("INSERT INTO {} (idx, embedding) VALUES (%s, %s)").format(table),
                    [(i, v) for i, v in enumerate(vectors)],
                )

    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        import psycopg
        from pgvector.psycopg import register_vector
        from psycopg import sql

        with psycopg.connect(self._dsn) as conn:
            register_vector(conn)
            rows = conn.execute(
                sql.SQL(
                    "SELECT idx, 1 - (embedding <=> %s) AS sim FROM {} ORDER BY embedding <=> %s LIMIT %s"
                ).format(sql.Identifier(self._table)),
                (query_vec, query_vec, k),
            ).fetchall()
        return [(int(i), float(s)) for i, s in rows]


def make_vector_index(
    settings, embedder, texts: list[str], attempts: int = 6, delay_s: float = 1.5, namespace: str = ""
) -> VectorIndex:
    """pgvector when DATABASE_URL is set and reachable, otherwise the local index.

    Postgres commonly starts a few seconds after the app in docker-compose, so connection
    failures are retried with a growing delay before falling back (loudly) to the local index."""
    local = LocalVectorIndex.build(texts, embedder.embed, embedder.name, settings.cache_dir)
    if not settings.database_url:
        return local
    for attempt in range(1, attempts + 1):
        try:
            return PgVectorIndex(settings.database_url, local.vectors, namespace)
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
