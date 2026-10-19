import re

import numpy as np
from rank_bm25 import BM25Okapi

_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOP = frozenset(
    "a an the of to in on for and or is are be by with at as it this that from "
    "i me my we our you your he his she her they their am was were been being do does did have has had will would "
    "can could should may might if then than so also what which who whom how when where why".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class BM25Index:
    def __init__(self, texts: list[str]):
        self._bm25 = BM25Okapi([tokenize(t) or ["_"] for t in texts])
        self._n = len(texts)

    def scores(self, query: str) -> np.ndarray:
        toks = tokenize(query)
        if not toks:
            return np.zeros(self._n, dtype=np.float32)
        return np.asarray(self._bm25.get_scores(toks), dtype=np.float32)

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        s = self.scores(query)
        order = np.argsort(-s)[:k]
        return [(int(i), float(s[i])) for i in order if s[i] > 0]
