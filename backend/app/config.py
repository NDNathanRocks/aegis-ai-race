from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str | None = None
    groq_heavy_model: str = "llama-3.3-70b-versatile"
    groq_fast_model: str = "llama-3.1-8b-instant"
    redis_url: str | None = None
    database_url: str | None = None  # enables pgvector
    cors_origins: str = "http://localhost:3000"
    cache_threshold: float = 0.92
    embedding_backend: str = "fastembed"  # "fastembed" | "hashing" (tests / offline)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    force_demo: bool = False
    corpus_dir: Path = BACKEND_DIR / "data" / "corpus"
    cache_dir: Path = BACKEND_DIR / ".cache"
    rate_limit_per_min: int = 30
    enterprise_usd_per_million: float = 15.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
