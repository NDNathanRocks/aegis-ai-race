"""Embedding backends. All return L2-normalised float32 vectors."""
import hashlib
import os
import re
import threading
from collections import OrderedDict
from typing import Callable, Protocol

# One ONNX/BLAS thread: under a CFS CPU quota (e.g. 0.1 vCPU on a many-core host) extra intra-op threads only
# fight over the quota. Must be set before onnxruntime / numpy's BLAS are first loaded, so it lives at import time.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


class VectorLRU:
    """Thread-safe text -> unit-vector LRU. Repeated queries (presets, paraphrases, decomposed sub-queries,
    sanitized variants) never touch the model after warm-up."""

    def __init__(self, maxsize: int = 1024):
        self.maxsize = maxsize
        self._d: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def embed(self, texts: list[str], compute: Callable[[list[str]], np.ndarray]) -> np.ndarray:
        out: list[np.ndarray | None] = [None] * len(texts)
        missing: list[int] = []
        with self._lock:
            for i, t in enumerate(texts):
                v = self._d.get(t)
                if v is None:
                    missing.append(i)
                else:
                    self._d.move_to_end(t)
                    out[i] = v
            self.hits += len(texts) - len(missing)
            self.misses += len(missing)
        if missing:
            uniq = list(dict.fromkeys(texts[i] for i in missing))
            vecs = compute(uniq)
            with self._lock:
                for t, v in zip(uniq, vecs, strict=True):
                    self._d[t] = v
                while len(self._d) > self.maxsize:
                    self._d.popitem(last=False)
            lookup = dict(zip(uniq, vecs, strict=True))
            for i in missing:
                out[i] = lookup[texts[i]]
        return np.stack(out) if out else np.zeros((0, 0), dtype=np.float32)  # type: ignore[arg-type]


class FastEmbedder:
    """BAAI/bge-small-en-v1.5 quantized ONNX running on CPU (single-threaded, with a per-text vector LRU)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", threads: int | None = 1, cache_size: int = 1024):
        from fastembed import TextEmbedding

        self.name = model_name
        self._model = TextEmbedding(model_name=model_name, threads=threads)
        self._lock = threading.Lock()  # ONNX session use is serialised for safety
        self.dim = int(next(iter(self._model.embed(["dim probe"]))).shape[0])
        self.lru = VectorLRU(cache_size)

    def _compute(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            vecs = np.array(list(self._model.embed(texts)), dtype=np.float32)
        return _normalize(vecs)

    def embed(self, texts: list[str]) -> np.ndarray:
        return self.lru.embed(texts, self._compute)


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
        self.lru = VectorLRU(1024)

    def _tokens(self, text: str) -> list[str]:
        return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]

    def embed(self, texts: list[str]) -> np.ndarray:
        return self.lru.embed(texts, self._compute)

    def _compute(self, texts: list[str]) -> np.ndarray:
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
