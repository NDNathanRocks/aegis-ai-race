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
    rate_limit_meta_per_min: int = 120  # knowledge-base / cache-reset routes (they hit disk or mutate state)
    sim_time_scale: float = 1.0  # 0 = instant (tests); 1 = realistic pacing
    enterprise_usd_per_million: float = 15.0
    cost_ratio_8b: float = 1 / 15  # per-token price of the 8B tier relative to 70B (enterprise cost model)

    # --- Groq parity policy (docs/contract-v2.md section 5) ---
    groq_retry_budget_s: float = 8.0  # total time a call may spend backing off / queueing before the race degrades
    groq_backoff_base_s: float = 0.5  # 0.5 -> 1 -> 2 s, capped by the budget and floored by retry-after
    groq_max_retries: int = 3
    groq_concurrency: int = 2  # asyncio.Semaphore per race
    groq_stagger_ms: float = 150.0  # engineered side's first Groq call starts this long after the race
    groq_stagger_jitter_ms: float = 50.0
    race_ttl_s: float = 120.0
    race_registry_max: int = 512

    # --- Security ---
    trust_proxy: bool = False  # honour X-Forwarded-For only behind a proxy we control (TRUST_PROXY=1)
    trusted_proxy_hops: int = 1  # how many right-most XFF entries were appended by our own proxies
    rate_limit_live_per_min: int = 6  # live (Groq) races per client per minute; beyond it races run in demo mode

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
