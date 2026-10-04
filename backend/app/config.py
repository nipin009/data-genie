"""Environment-based configuration. No schema hardcoded; DB URL is configurable."""
import os
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Resolve against this source file so `uvicorn` may be started from either
    # repository root or backend/ while consistently loading the root .env.
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Primary store: local Postgres database "local_db" (dg_-prefixed tables).
    # Host Postgres runs on the default socket; override via DATABASE_URL env.
    DATABASE_URL: str = "postgresql+psycopg2://nipinmishra@/local_db?host=/tmp"
    TABLE_PREFIX: str = "dg_"
    GOOGLE_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    LLM_TIMEOUT_SECONDS: int = 30

    LANGSMITH_TRACING: bool = False
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_PROJECT: str = "data-genie-text2sql"

    QUERY_TIMEOUT_MS: int = 15000
    LOCK_TIMEOUT_MS: int = 3000
    MAX_ROWS: int = 500
    MAX_REPAIR_RETRIES: int = 2
    # 0 disables the optional PostgreSQL EXPLAIN cost ceiling.
    MAX_QUERY_COST: float = 0
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10
    LLM_SUMMARIZER: bool = False
    ALLOW_SQL_PREVIEW: bool = True
    # Writes are deliberately off by default. Enabling requires both this flag
    # and API-key authentication; mutations still require per-request approval.
    ENABLE_MUTATIONS: bool = False
    MUTATION_APPROVAL_TTL_SECONDS: int = 300
    # Test/demo compatibility only. Production generic Text-to-SQL must use
    # Gemini; this flag is false unless explicitly enabled.
    ALLOW_DETERMINISTIC_FALLBACK: bool = False

    # Disabled for local development. In production set AUTH_ENABLED=true and
    # provide comma-separated `secret:role` pairs.
    API_KEYS: str = ""
    AUTH_ENABLED: bool = False

    LOG_LEVEL: str = "INFO"
    FRONTEND_ORIGIN: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Honour explicit env even when .env absent; pydantic-settings already does this.
    # Allow DATABASE_URL override via plain env var name DATABASE_URL.
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        s.DATABASE_URL = env_url
    return s
