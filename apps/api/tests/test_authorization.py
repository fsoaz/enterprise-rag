"""Regression tests for the authorization defects found in review.

Each of these passed silently before: the checks they cover did not exist.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.integration_database import integration_database_urls

from api.deps.auth import reset_auth_caches
from api.settings import clear_settings_cache
from db.session import reset_engine

pytestmark = pytest.mark.integration


def _migrate_url() -> str:
    return integration_database_urls()[1]


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


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    import asyncio

    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
    monkeypatch.setenv("INGEST_SYNC", "true")
    app_url, migrate_url = integration_database_urls()
    monkeypatch.setenv("DATABASE_URL", app_url)
    monkeypatch.setenv("DATABASE_URL_MIGRATE", migrate_url)
    clear_settings_cache()
    reset_engine()
    if not asyncio.run(_db_reachable(app_url)):
        pytest.skip("database unreachable")
    asyncio.run(reset_auth_caches())
    from api.main import app

    with TestClient(app) as c:
        yield c
    asyncio.run(reset_auth_caches())
    reset_engine()
    clear_settings_cache()


def _headers(user: str) -> dict[str, str]:
    return {"X-Dev-User": user}


def _collection_id(client: TestClient, user: str, name: str) -> str:
    response = client.get("/api/v1/collections", headers=_headers(user))
    assert response.status_code == 200, response.text
    match = next((c for c in response.json()["data"] if c["name"] == name), None)
    assert match is not None, f"expected seeded collection {name!r}"
    return str(match["id"])


async def _purge_collection(name: str) -> None:
    engine = create_async_engine(_migrate_url())
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.current_tenant', '', false)"))
            await conn.execute(text("DELETE FROM collections WHERE name = :name"), {"name": name})
    finally:
        await engine.dispose()


async def _purge_collections_with_prefix(prefix: str) -> None:
    engine = create_async_engine(_migrate_url())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM collections WHERE name LIKE :prefix"),
                {"prefix": f"{prefix}%"},
            )
    finally:
        await engine.dispose()


async def _create_query_fixture(subject: str) -> str:
    """Insert only the ownership record this feedback test needs.

    Creating it through /chat/completions coupled a feedback authorization test
    to embedding, retrieval, inference startup, SSE parsing, and generation. CI's
    database integration job deliberately provides none of those services.
    """
    engine = create_async_engine(_migrate_url())
    query_id = uuid4()
    try:
        async with engine.begin() as conn:
            owner = (
                await conn.execute(
                    text(
                        "SELECT id, tenant_id FROM users "
                        "WHERE external_subject = :subject AND status = 'active'"
                    ),
                    {"subject": subject},
                )
            ).one()
            await conn.execute(
                text(
                    "INSERT INTO queries "
                    "(id, tenant_id, user_id, question, language, strategy) "
                    "VALUES (:id, :tenant_id, :user_id, :question, 'en', 'hybrid_rrf')"
                ),
                {
                    "id": query_id,
                    "tenant_id": owner.tenant_id,
                    "user_id": owner.id,
                    "question": "feedback ownership regression fixture",
                },
            )
    finally:
        await engine.dispose()
    return str(query_id)


async def _purge_query(query_id: str) -> None:
    engine = create_async_engine(_migrate_url())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM queries WHERE id = CAST(:id AS uuid)"), {"id": query_id}
            )
    finally:
        await engine.dispose()


def test_duplicate_collection_name_is_a_conflict(client: TestClient) -> None:
    """Was an unhandled IntegrityError surfacing as a generic 500."""
    import asyncio

    name = "ConflictProbe"
    # Purge first too: an interrupted earlier run would otherwise leave the row
    # behind and make this test fail on its own residue.
    asyncio.run(_purge_collection(name))
    try:
        first = client.post(
            "/api/v1/collections", headers=_headers("acme-admin"), json={"name": name}
        )
        assert first.status_code == 201, first.text
        second = client.post(
            "/api/v1/collections", headers=_headers("acme-admin"), json={"name": name}
        )
        assert second.status_code == 409, second.text
        assert second.json()["title"] == "Conflict"
    finally:
        # No collection-delete endpoint exists, so clean up directly rather than
        # leaving probe rows in the tenant the eval harness scores.
        asyncio.run(_purge_collection(name))


def test_collection_keyset_pagination_has_no_gaps_or_duplicates(client: TestClient) -> None:
    import asyncio

    prefix = f"PageProbe-{uuid4().hex[:8]}-"
    try:
        for index in range(3):
            created = client.post(
                "/api/v1/collections",
                headers=_headers("acme-admin"),
                json={"name": f"{prefix}{index}"},
            )
            assert created.status_code == 201, created.text

        seen: list[str] = []
        all_names: list[str] = []
        cursor: str | None = None
        for _ in range(10):
            params: dict[str, str | int] = {"limit": 2}
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get(
                "/api/v1/collections",
                headers=_headers("acme-admin"),
                params=params,
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            ids = [row["id"] for row in payload["data"]]
            assert not set(ids).intersection(seen)
            seen.extend(ids)
            all_names.extend(row["name"] for row in payload["data"])
            cursor = payload["next_cursor"]
            if cursor is None:
                break
        else:
            pytest.fail("collection cursor did not terminate")

        assert len(seen) == len(set(seen))
        # All three probes must be reachable even though each page holds two rows.
        assert {f"{prefix}{index}" for index in range(3)}.issubset(all_names)
    finally:
        asyncio.run(_purge_collections_with_prefix(prefix))


def test_binary_upload_declared_as_text_is_rejected(client: TestClient) -> None:
    """Content-Type was trusted, so any payload labelled text/plain got through."""
    collection_id = _collection_id(client, "acme-admin", "Acme Policies")
    response = client.post(
        "/api/v1/documents",
        headers=_headers("acme-admin"),
        files={"file": ("payload.exe", b"MZ\x90\x00\x03\x04\x00\x00", "text/plain")},
        data={"collection_id": collection_id},
    )
    assert response.status_code == 415, response.text


def test_feedback_rejects_another_users_query(client: TestClient) -> None:
    """Tenant scoping alone let any member rate any other member's query."""
    import asyncio

    query_id = asyncio.run(_create_query_fixture("acme-member"))
    try:
        stolen = client.post(
            "/api/v1/feedback",
            headers=_headers("acme-viewer"),
            json={"query_id": query_id, "rating": "down"},
        )
        assert stolen.status_code == 404, stolen.text

        owned = client.post(
            "/api/v1/feedback",
            headers=_headers("acme-member"),
            json={"query_id": query_id, "rating": "up"},
        )
        assert owned.status_code == 201, owned.text
        # Re-submitting updates the existing vote rather than stacking rows.
        again = client.post(
            "/api/v1/feedback",
            headers=_headers("acme-member"),
            json={"query_id": query_id, "rating": "down"},
        )
        assert again.status_code == 200, again.text
        assert again.json()["id"] == owned.json()["id"]
    finally:
        asyncio.run(_purge_query(query_id))


def test_erase_requires_admin(client: TestClient) -> None:
    documents = client.get("/api/v1/documents", headers=_headers("acme-admin"))
    assert documents.status_code == 200
    data = documents.json()["data"]
    if not data:
        pytest.skip("no documents available to test erasure authorization")
    document_id = data[0]["id"]
    response = client.post(
        f"/api/v1/admin/documents/{document_id}/erase",
        headers=_headers("acme-member"),
        json={"reason": "should be refused", "legal_basis": "n/a"},
    )
    assert response.status_code == 403, response.text
