from typing import Any, Dict, Optional
from pydantic import PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )

    PROJECT_NAME: str = "SlicedLLM"
    ENVIRONMENT: str = "development"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str

    LOG_LEVEL: str = "INFO"

    # Database
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    DATABASE_URL: Optional[str] = None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: Optional[str], info: Any) -> Any:
        if isinstance(v, str) and v:
            return v
        
        # Access preceding fields via info.data since v is None/not provided
        data = info.data
        user = data.get("POSTGRES_USER")
        password = data.get("POSTGRES_PASSWORD")
        server = data.get("POSTGRES_SERVER")
        port = data.get("POSTGRES_PORT")
        db = data.get("POSTGRES_DB")
        
        return f"postgresql+asyncpg://{user}:{password}@{server}:{port}/{db}"

    # LLM Keys
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    COHERE_API_KEY: Optional[str] = None

    # Ollama Configuration
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_TIMEOUT: float = 120.0
    OLLAMA_MAX_RETRIES: int = 3
    OLLAMA_MAX_CONCURRENT_REQUESTS: int = 10

    # Groq Configuration
    GROQ_API_KEY: Optional[str] = None
    GROQ_BASE_URL: str = "https://api.groq.com"
    GROQ_TIMEOUT: float = 120.0
    GROQ_MAX_RETRIES: int = 3
    GROQ_MAX_CONCURRENT_REQUESTS: int = 10

    # Evaluation Configuration
    EVALUATION_MAX_CONCURRENT: int = 10
    EVALUATION_DEFAULT_TIMEOUT: float = 120.0
    EVALUATION_ENABLE_JUDGE: bool = False


settings = Settings()
