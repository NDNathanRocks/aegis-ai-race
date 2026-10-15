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
