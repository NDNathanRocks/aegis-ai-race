"""Embedding backends. All return L2-normalised float32 vectors."""
import hashlib
import re
import threading
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


class FastEmbedder:
    """BAAI/bge-small-en-v1.5 quantized ONNX running on CPU."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding

        self.name = model_name
        self._model = TextEmbedding(model_name=model_name)
        self._lock = threading.Lock()  # ONNX session use is serialised for safety
        self.dim = int(next(iter(self._model.embed(["dim probe"]))).shape[0])

    def embed(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            vecs = np.array(list(self._model.embed(texts)), dtype=np.float32)
        return _normalize(vecs)


_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOP = frozenset("a an the of to in on for and or is are be by with at as it this that from".split())


class HashingEmbedder:
    """Deterministic bag-of-words hashing embedder (unigrams + bigrams).

    Offline test double: no model download, stable across runs, and still
    captures lexical overlap well enough to test retrieval and cache plumbing.
    It is *not* used in production unless EMBEDDING_BACKEND=hashing.
    """

    def __init__(self, dim: int = 512):
        self.name = f"hashing-{dim}"
        self.dim = dim

    def _tokens(self, text: str) -> list[str]:
        return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            toks = self._tokens(text)
            grams = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False)]
            for g in grams:
                h = int.from_bytes(hashlib.md5(g.encode()).digest()[:8], "little")
                out[i, h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        return _normalize(out)


_embedder: Embedder | None = None
_embedder_key: tuple[str, str] | None = None


def get_embedder(backend: str = "fastembed", model: str = "BAAI/bge-small-en-v1.5") -> Embedder:
    global _embedder, _embedder_key
    key = (backend, model)
    if _embedder is None or _embedder_key != key:
        _embedder = HashingEmbedder() if backend == "hashing" else FastEmbedder(model)
        _embedder_key = key
    return _embedder
