from __future__ import annotations

import pytest

from tests.integration_database import integration_database_urls


def test_integration_database_requires_explicit_test_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL_MIGRATE", raising=False)
    # Ambient application URLs must never become an implicit test target.
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://rag_app:rag_app@localhost:15432/enterprise_rag",
    )
    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL"):
        integration_database_urls()


def test_integration_database_rejects_development_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://rag_app:rag_app@localhost:15432/enterprise_rag",
    )
    monkeypatch.setenv(
        "TEST_DATABASE_URL_MIGRATE",
        "postgresql+psycopg://rag_migrate:rag_migrate@localhost:15432/enterprise_rag",
    )
    with pytest.raises(RuntimeError, match="Refusing integration database"):
        integration_database_urls()


def test_integration_database_accepts_matching_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://rag_app:rag_app@localhost:15432/enterprise_rag_test",
    )
    monkeypatch.setenv(
        "TEST_DATABASE_URL_MIGRATE",
        "postgresql+psycopg://rag_migrate:rag_migrate@localhost:15432/enterprise_rag_test",
    )
    app_url, migrate_url = integration_database_urls()
    assert app_url.endswith("/enterprise_rag_test")
    assert migrate_url.startswith("postgresql+asyncpg://")
