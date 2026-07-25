"""Regression tests for the authorization defects found in review.

Each of these passed silently before: the checks they cover did not exist.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from api.deps.auth import reset_auth_caches
from api.settings import clear_settings_cache
from db.session import reset_engine

pytestmark = pytest.mark.integration

_APP = "postgresql+asyncpg://rag_app:rag_app@localhost:15432/enterprise_rag"
_MIGRATE = "postgresql+asyncpg://rag_migrate:rag_migrate@localhost:15432/enterprise_rag"


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
    monkeypatch.setenv("DATABASE_URL", os.environ.get("DATABASE_URL", _APP))
    monkeypatch.setenv("DATABASE_URL_MIGRATE", os.environ.get("DATABASE_URL_MIGRATE", _MIGRATE))
    clear_settings_cache()
    reset_engine()
    if not asyncio.run(_db_reachable(os.environ["DATABASE_URL"])):
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
    engine = create_async_engine(os.environ.get("DATABASE_URL_MIGRATE", _MIGRATE))
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.current_tenant', '', false)"))
            await conn.execute(text("DELETE FROM collections WHERE name = :name"), {"name": name})
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
    chat = client.post(
        "/api/v1/chat/completions",
        headers=_headers("acme-member"),
        json={"question": "authorization regression probe", "stream": True},
    )
    assert chat.status_code == 200, chat.text
    query_id = None
    for line in chat.text.splitlines():
        if line.startswith("data:") and "query_id" in line:
            import json

            query_id = json.loads(line[len("data:") :].strip())["query_id"]
    assert query_id, "expected a query_id from the chat stream"

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
