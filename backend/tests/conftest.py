import os

# Force offline, deterministic behaviour before the app is imported.
os.environ["EMBEDDING_BACKEND"] = "hashing"
os.environ["GROQ_API_KEY"] = ""
os.environ["REDIS_URL"] = ""
os.environ["DATABASE_URL"] = ""

import pytest  # noqa: E402

from app.config import Settings  # noqa: E402
from app.rag.corpus import load_chunks  # noqa: E402
from app.rag.embeddings import HashingEmbedder  # noqa: E402
from app.rag.hybrid import HybridRetriever  # noqa: E402
from app.rag.vector_index import LocalVectorIndex  # noqa: E402


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(groq_api_key=None, redis_url=None, database_url=None, embedding_backend="hashing")


@pytest.fixture(scope="session")
def embedder() -> HashingEmbedder:
    return HashingEmbedder()


@pytest.fixture(scope="session")
def chunks(settings):
    return load_chunks(settings.corpus_dir)


@pytest.fixture(scope="session")
def retriever(chunks, embedder) -> HybridRetriever:
    index = LocalVectorIndex(embedder.embed([c.text for c in chunks]))
    return HybridRetriever(chunks, embedder, index)


# --- real-model support ------------------------------------------------------------------------
def _load_real_embedder():
    try:
        from app.rag.embeddings import FastEmbedder

        return FastEmbedder()
    except Exception:  # offline / no model cache
        return None


REAL_EMBEDDER = _load_real_embedder()


def pytest_collection_modifyitems(config, items):
    if REAL_EMBEDDER is None:
        skip = pytest.mark.skip(reason="fastembed model unavailable (offline)")
        for item in items:
            if "model" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(scope="session")
def e2e_settings() -> Settings:
    """Settings for end-to-end tests: real embeddings, instant simulator, no external services."""
    return Settings(
        groq_api_key=None, redis_url=None, database_url=None, embedding_backend="fastembed",
        sim_time_scale=0.0, rate_limit_per_min=10_000,
    )


@pytest.fixture(scope="session")
def app_client(e2e_settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(e2e_settings)) as c:
        yield c


def parse_sse(response) -> list[tuple[str, dict]]:
    import json

    events, name = [], None
    for line in response.iter_lines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            events.append((name, json.loads(line[5:])))
    return events


@pytest.fixture
def run_race(app_client):
    import itertools

    counter = itertools.count()

    def _run(side: str, query: str, preset_id=None, session_id=None, **extra):
        body = {"query": query, "preset_id": preset_id, "session_id": session_id or f"s{next(counter)}", **extra}
        with app_client.stream("POST", f"/api/race/{side}", json=body) as r:
            assert r.status_code == 200
            return parse_sse(r)

    return _run
