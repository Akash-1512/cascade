"""Application settings loaded from environment variables.

All configuration flows through ``Settings``. Modules should never read ``os.environ``
directly — import ``get_settings()`` instead.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the cascade service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ------------------------------------------------------
    cascade_env: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    secret_key: SecretStr = Field(default=SecretStr("change-me-in-production"))
    access_token_expire_minutes: int = 60

    # --- Storage ----------------------------------------------------------
    database_url: str = "postgresql+psycopg://cascade:cascade@localhost:5432/cascade"
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection: str = "cascade_memory"

    # --- LLM provider -----------------------------------------------------
    groq_api_key: SecretStr | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    together_api_key: SecretStr | None = None
    together_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

    # --- Embeddings -------------------------------------------------------
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # --- Observability ----------------------------------------------------
    langsmith_tracing: bool = True
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "cascade"

    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_experiment: str = "cascade-evals"

    # --- MCP server -------------------------------------------------------
    mcp_host: str = "0.0.0.0"  # noqa: S104 — bind all interfaces inside container
    mcp_port: int = 8765
    mcp_auth_required: bool = True

    # --- REST API ---------------------------------------------------------
    api_auth_mode: Literal["dev", "jwt"] = "dev"
    api_cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])
    # JWT verification (only used when api_auth_mode='jwt')
    api_jwks_url: str | None = None
    api_jwt_issuer: str | None = None
    api_jwt_audience: str | None = None
    api_jwks_cache_ttl_seconds: int = 3600

    @property
    def is_production(self) -> bool:
        """Return ``True`` when running in production environment."""
        return self.cascade_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    Cached so repeated lookups don't re-parse the environment. Tests that need a fresh
    instance should call ``get_settings.cache_clear()``.
    """
    return Settings()
