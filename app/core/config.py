from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )

    PROJECT_NAME: str = "SlicedLLM"
    ENVIRONMENT: str = "development"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "dev-only-change-me"
    LOG_LEVEL: str = "INFO"

    # Optional shared API key. When set, every /api request must send `X-API-Key`.
    API_KEY: str | None = None
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "slicedllm"
    DATABASE_URL: str | None = None
    # Create tables (incl. triggers) on startup. Use Alembic (`alembic upgrade head`) in real
    # deployments.
    AUTO_CREATE_SCHEMA: bool = True

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: str | None, info: Any) -> Any:
        if isinstance(v, str) and v:
            return v
        data = info.data
        return (
            f"postgresql+asyncpg://{data.get('POSTGRES_USER')}:{data.get('POSTGRES_PASSWORD')}"
            f"@{data.get('POSTGRES_SERVER')}:{data.get('POSTGRES_PORT')}/{data.get('POSTGRES_DB')}"
        )

    # Ollama (local provider)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_TIMEOUT: float = 120.0
    OLLAMA_MAX_CONCURRENT_REQUESTS: int = 10

    # Groq (OpenAI-compatible cloud provider)
    GROQ_API_KEY: str | None = None
    GROQ_BASE_URL: str = "https://api.groq.com"
    GROQ_TIMEOUT: float = 120.0
    GROQ_MAX_CONCURRENT_REQUESTS: int = 10

    # Evaluation defaults (each run records the values it actually used)
    EVALUATION_CASE_CONCURRENCY: int = 4
    EVALUATION_MAX_INFLIGHT_REQUESTS: int = 8
    EVALUATION_REQUESTS_PER_SECOND: float = 0.0  # 0 = unlimited
    EVALUATION_CALL_TIMEOUT: float = 120.0
    EVALUATION_MAX_RETRIES: int = 3
    EVALUATION_BACKOFF_BASE: float = 1.0
    EVALUATION_MAX_CASES_PER_RUN: int = 500
    JUDGE_MAX_ATTEMPTS: int = 3
    DEFAULT_JUDGE_PROVIDER: str | None = None  # falls back to the candidate provider
    DEFAULT_JUDGE_MODEL: str | None = None  # falls back to the candidate model

    # Durable job runner (DB-backed)
    RUN_WORKER_IN_APP: bool = True
    JOB_POLL_INTERVAL: float = 1.0
    JOB_HEARTBEAT_INTERVAL: float = 5.0
    JOB_STALE_SECONDS: float = 60.0
    JOB_MAX_ATTEMPTS: int = 3
    # Single-worker assumption: at boot, RUNNING runs can only be orphans from a dead process.
    JOB_RECOVER_ON_STARTUP: bool = True


settings = Settings()
