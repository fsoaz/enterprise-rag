from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps.auth import reset_auth_caches
from api.main import app
from api.settings import clear_settings_cache
from db.models import User
from db.session import reset_engine, set_tenant_context

_LOCAL_APP = "postgresql+asyncpg://rag_app:rag_app@localhost:15432/enterprise_rag"
_LOCAL_MIGRATE = "postgresql+asyncpg://rag_migrate:rag_migrate@localhost:15432/enterprise_rag"


def _app_url() -> str:
    if url := os.environ.get("TEST_DATABASE_URL"):
        return url
    if os.environ.get("CI") == "true":
        return os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://rag_app:rag_app@localhost:5432/enterprise_rag",
        )
    return _LOCAL_APP


def _migrate_url() -> str:
    if url := os.environ.get("TEST_DATABASE_URL_MIGRATE"):
        return _to_async(url)
    if os.environ.get("CI") == "true":
        return _to_async(
            os.environ.get(
                "DATABASE_URL_MIGRATE",
                "postgresql+psycopg://rag_migrate:rag_migrate@localhost:5432/enterprise_rag",
            )
        )
    return _LOCAL_MIGRATE


def _to_async(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def _db_reachable(url: str) -> bool:
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


def test_me_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """401 without credentials — no DB required when auth header is absent."""
    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
    clear_settings_cache()
    reset_engine()
    with TestClient(app) as client:
        response = client.get("/api/v1/me")
    assert response.status_code == 401
    body = response.json()
    assert body["status"] == 401
    assert "request_id" in body
    assert response.headers.get("X-Request-Id") == body["request_id"]


@pytest.fixture
def auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
    monkeypatch.setenv("DATABASE_URL", _app_url())
    monkeypatch.setenv("DATABASE_URL_MIGRATE", _migrate_url())
    clear_settings_cache()
    reset_engine()


@pytest.fixture
async def client(auth_env: None) -> TestClient:
    pytest.importorskip("asyncpg")
    if not await _db_reachable(_migrate_url()):
        pytest.skip("database unreachable")
    await reset_auth_caches()
    with TestClient(app) as test_client:
        yield test_client
    await reset_auth_caches()
    reset_engine()
    clear_settings_cache()


@pytest.mark.integration
def test_me_dev_header(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers={"X-Dev-User": "acme-admin"})
    assert response.status_code == 200
    body = response.json()
    assert body["external_subject"] == "acme-admin"
    assert body["email"] == "admin@acme.example"
    assert "admin" in body["roles"]
    assert body["tenant_id"]


@pytest.mark.integration
def test_me_dev_bearer_token(client: TestClient) -> None:
    response = client.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer dev:globex-admin"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["external_subject"] == "globex-admin"
    assert "admin" in body["roles"]


@pytest.mark.integration
def test_acme_admin_cannot_see_globex_users_via_debug(client: TestClient) -> None:
    response = client.get("/api/v1/debug/users", headers={"X-Dev-User": "acme-admin"})
    assert response.status_code == 200
    subjects = {row["external_subject"] for row in response.json()}
    assert subjects
    assert all(s.startswith("acme-") for s in subjects)
    assert "globex-admin" not in subjects


@pytest.mark.integration
@pytest.mark.asyncio
async def test_acme_admin_cannot_see_globex_users_via_session(auth_env: None) -> None:
    if not await _db_reachable(_migrate_url()):
        pytest.skip("database unreachable")
    await reset_auth_caches()

    migrate_engine = create_async_engine(_migrate_url(), pool_pre_ping=True)
    app_engine = create_async_engine(_app_url(), pool_pre_ping=True)
    try:
        migrate_factory = async_sessionmaker(
            migrate_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with migrate_factory() as session:
            acme = await session.scalar(select(User).where(User.external_subject == "acme-admin"))
            assert acme is not None
            tenant_id = acme.tenant_id

        factory = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session, session.begin():
            await set_tenant_context(session, tenant_id)
            rows = (await session.scalars(select(User))).all()
            subjects = {u.external_subject for u in rows}
            assert subjects
            assert all(s.startswith("acme-") for s in subjects)
            assert "globex-admin" not in subjects
    finally:
        await migrate_engine.dispose()
        await app_engine.dispose()
        await reset_auth_caches()
        reset_engine()
        clear_settings_cache()
