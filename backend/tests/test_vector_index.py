import numpy as np

from app.config import Settings
from app.rag.embeddings import HashingEmbedder
from app.rag.vector_index import LocalVectorIndex, make_vector_index


def test_local_index_returns_nearest_first():
    v = np.eye(3, dtype=np.float32)
    idx = LocalVectorIndex(v)
    assert idx.search(np.array([0, 1, 0], dtype=np.float32), 2)[0] == (1, 1.0)


def test_local_index_is_persisted_by_content_hash(tmp_path):
    e = HashingEmbedder()
    calls = []

    def embed(texts):
        calls.append(1)
        return e.embed(texts)

    a = LocalVectorIndex.build(["x y", "z"], embed, e.name, tmp_path)
    b = LocalVectorIndex.build(["x y", "z"], embed, e.name, tmp_path)
    assert len(calls) == 1 and np.allclose(a.vectors, b.vectors)
    LocalVectorIndex.build(["different"], embed, e.name, tmp_path)
    assert len(calls) == 2


def test_unreachable_postgres_retries_then_falls_back_loudly(tmp_path, caplog):
    s = Settings(database_url="postgresql://aegis:aegis@127.0.0.1:1/aegis", cache_dir=tmp_path)
    e = HashingEmbedder()
    with caplog.at_level("INFO", logger="aegis.vector_index"):
        idx = make_vector_index(s, e, ["a b", "c d"], attempts=3, delay_s=0.0)
    assert isinstance(idx, LocalVectorIndex)
    assert "attempt 1/3" in caplog.text and "using the local vector index" in caplog.text
