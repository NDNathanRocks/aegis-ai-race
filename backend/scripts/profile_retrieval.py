"""Profile where retrieval time goes: embed vs BM25 vs vector search.

    python scripts/profile_retrieval.py [--domain b2b_sla] [--threads N] [--n 30]

Prints a Markdown table. Run it inside `docker run --cpus=0.1` to reproduce a throttled host.
`--threads 0` keeps fastembed's default (all visible cores); anything else is passed through.
"""
import argparse
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

QUERY = (
    "Audit Northwind Cloud Invoice INV-2291: Billed $48,000 for Managed Kubernetes, applied a 10% SLA credit "
    "(-$4,800) for 99.62% monthly uptime, and added $2,400 for 24x7 Premium Support, totaling $45,600. "
    "Verify every line item against the Master SLA and calculate the exact approved payout."
)


def throttle_cpu(cores: float) -> None:
    """Emulate a CFS quota of `cores` vCPU on Windows (no Docker): job-object hard CPU cap across ALL host cores.

    Threads still see every core (like a container), but total CPU time is capped. Approximation only; a real
    `docker run --cpus=0.1` is the reference measurement."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    class RATE(ctypes.Structure):
        _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]
    info = RATE(0x1 | 0x4, max(1, int(cores / (os.cpu_count() or 1) * 10000)))  # ENABLE | HARD_CAP
    if not k32.SetInformationJobObject(job, 15, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error())
    if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error())


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def stats(label, xs):
    return f"| {label} | {statistics.median(xs):.1f} | {pct(xs, 95):.1f} | {max(xs):.1f} |"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="b2b_sla")
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--after", action="store_true", help="measure the shipped path: prebuilt index + warm caches")
    ap.add_argument("--cache-dir", default=None, help="prebuilt index dir (python -m app.rag.prebuild --cache-dir ...)")
    ap.add_argument("--throttle", type=float, default=0.0, help="emulate this many vCPU (Windows job-object cap)")
    a = ap.parse_args()
    if a.throttle:
        throttle_cpu(a.throttle)
    if a.threads:
        for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            os.environ[v] = str(a.threads)

    from app.config import BACKEND_DIR

    if a.after:
        return after(a)
    from app.rag.bm25 import BM25Index
    from app.rag.corpus import load_chunks
    from app.rag.hybrid import HybridRetriever, split_subqueries
    from app.rag.vector_index import LocalVectorIndex

    corpus = BACKEND_DIR / "data" / "corpus"
    ddir = corpus / a.domain if (corpus / a.domain).is_dir() else corpus
    chunks = load_chunks(ddir)
    texts = [c.text for c in chunks]

    t = time.perf_counter()
    from app.rag.embeddings import FastEmbedder

    try:
        emb = FastEmbedder(threads=a.threads or None)
    except TypeError:
        emb = FastEmbedder()
    load_ms = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    emb.embed(["x"])
    first_probe = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    emb.embed([QUERY])
    first_real = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    vecs = emb.embed(texts)
    index_ms = (time.perf_counter() - t) * 1000
    index = LocalVectorIndex(vecs)
    bm25 = BM25Index(texts)
    ret = HybridRetriever(chunks, emb, index)

    embed_ms, vec_ms, bm_ms, full_ms, dec_ms = [], [], [], [], []
    subs = split_subqueries(QUERY)
    for _ in range(a.n):
        t = time.perf_counter(); qv = emb.embed([QUERY])[0]; embed_ms.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter(); index.search(qv, 10); vec_ms.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter(); bm25.search(QUERY, 10); bm_ms.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter(); ret.retrieve(QUERY, k=4); full_ms.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter(); ret.retrieve(QUERY, k=4, decompose=True); dec_ms.append((time.perf_counter() - t) * 1000)

    print(f"domain={a.domain} chunks={len(chunks)} cpu_count={os.cpu_count()} threads={a.threads or 'default'} throttle={a.throttle or 'none'} n={a.n}")
    print(f"model load {load_ms:.0f} ms | first embed (probe) {first_probe:.0f} ms | first embed (real query) {first_real:.0f} ms | "
          f"embed all {len(texts)} chunks {index_ms:.0f} ms | sub-queries {len(subs)}")
    print("\n| step | median ms | p95 ms | max ms |\n|---|---:|---:|---:|")
    for lbl, xs in (("embed query", embed_ms), ("vector search", vec_ms), ("BM25 search", bm_ms),
                    ("retrieve() total", full_ms), ("retrieve(decompose) total", dec_ms)):
        print(stats(lbl, xs))


def after(a):
    """Shipped path: FastEmbedder(threads=1) + prebuilt per-domain index + preset/paraphrase caches warmed."""
    from pathlib import Path

    from app import domains as dom
    from app.config import Settings
    from app.rag.embeddings import FastEmbedder

    t0 = time.perf_counter()
    emb = FastEmbedder(threads=1)
    t_model = time.perf_counter()
    settings = Settings(embedding_backend="fastembed", cache_dir=Path(a.cache_dir) if a.cache_dir else Settings().cache_dir)
    rts = dom.build_domains(settings, emb, warm=False)
    t_idx = time.perf_counter()
    stats = dom.warm_domains(rts, emb)
    t_warm = time.perf_counter()
    print(f"throttle={a.throttle or 'none'} cpu_count={os.cpu_count()}")
    print(f"model load {1000*(t_model-t0):.0f} ms | build_domains (prebuilt index) {1000*(t_idx-t_model):.0f} ms | "
          f"warm {1000*(t_warm-t_idx):.0f} ms | time-to-ready {1000*(t_warm-t0):.0f} ms | warm stats {stats}")
    preset, custom = [], []
    for rt in rts.values():
        for p in rt.spec.presets:
            for q in (p.query, p.paraphrase):
                if not q:
                    continue
                t = time.perf_counter()
                v = emb.embed([q])[0]
                rt.retriever.retrieve(q, 4, 10, "hybrid", v, True)
                preset.append((time.perf_counter() - t) * 1000)
        for i in range(a.n):  # unseen text: pays the embedding(s)
            q = rt.spec.presets[0].query.replace("exact", f"precise{i}", 1) + f" variant {i} {rt.spec.id}"
            t = time.perf_counter()
            v = emb.embed([q])[0]
            rt.retriever.retrieve(q, 4, 10, "hybrid", v, True)
            custom.append((time.perf_counter() - t) * 1000)
    print("\n| path | median ms | p95 ms | max ms |\n|---|---:|---:|---:|")
    print(stats_row("preset/paraphrase (warmed)", preset))
    print(stats_row("custom query (cold, decomposed)", custom))


def stats_row(label, xs):
    return stats(label, xs)


if __name__ == "__main__":
    main()
