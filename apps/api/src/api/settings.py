from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API runtime settings (env / .env)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://rag_app:rag_app@localhost:15432/enterprise_rag",
        description="Async app DB URL (rag_app, RLS enforced)",
    )
    database_url_migrate: str | None = Field(
        default="postgresql+asyncpg://rag_migrate:rag_migrate@localhost:15432/enterprise_rag",
        description="Sync/async migrate URL (BYPASSRLS) for identity bootstrap",
    )

    oidc_issuer: str = "http://localhost:8080/realms/enterprise-rag"
    oidc_audience: str = "enterprise-rag-api"
    oidc_jwks_url: str = "http://localhost:8080/realms/enterprise-rag/protocol/openid-connect/certs"
    oidc_jwks_cache_ttl_seconds: int = 3600

    # Local/tests without Keycloak: X-Dev-User / Bearer dev:<subject>
    dev_auth_bypass: bool = False

    anthropic_api_key: str = "sk-ant-replace-me"
    llm_primary_model: str = "claude-opus-5"
    llm_judge_model: str = "claude-haiku-4-5"
    llm_fallback_model: str = "claude-sonnet-5"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    def async_database_url(self) -> str:
        return _to_asyncpg(self.database_url)

    def async_identity_url(self) -> str:
        """URL for identity lookups that must see users without tenant GUC (BYPASSRLS)."""
        raw = self.database_url_migrate or self.database_url
        return _to_asyncpg(raw)


def _to_asyncpg(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
