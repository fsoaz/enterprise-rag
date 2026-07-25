"""Integration: sync ingest + lexical search. Skips if DB/MinIO/inference unavailable."""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import httpx
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


def _minio_reachable() -> bool:
    endpoint = os.environ.get("S3_ENDPOINT_URL", "http://localhost:19000")
    try:
        httpx.get(endpoint, timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


def _inference_reachable() -> bool:
    base = os.environ.get("INFERENCE_BASE_URL", "http://localhost:8001").rstrip("/")
    headers: dict[str, str] = {}
    token = os.environ.get("INFERENCE_SERVICE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = httpx.post(
            f"{base}/v1/embed",
            json={"texts": ["ping"], "mode": "passage"},
            headers=headers,
            timeout=5.0,
        )
    except httpx.HTTPError:
        return False
    if r.status_code == 401:
        # Reachable but misconfigured — surface it instead of silently skipping.
        raise RuntimeError(
            "inference rejected INFERENCE_SERVICE_TOKEN; check it matches the service"
        )
    return r.status_code == 200


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    import asyncio

    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
    monkeypatch.setenv("INGEST_SYNC", "true")
    monkeypatch.setenv("DATABASE_URL", os.environ.get("DATABASE_URL", _APP))
    monkeypatch.setenv(
        "DATABASE_URL_MIGRATE",
        os.environ.get("DATABASE_URL_MIGRATE", _MIGRATE),
    )
    monkeypatch.setenv(
        "S3_ENDPOINT_URL", os.environ.get("S3_ENDPOINT_URL", "http://localhost:19000")
    )
    monkeypatch.setenv(
        "INFERENCE_BASE_URL",
        os.environ.get("INFERENCE_BASE_URL", "http://localhost:8001"),
    )
    clear_settings_cache()
    reset_engine()

    if not asyncio.run(_db_reachable(os.environ["DATABASE_URL"])):
        pytest.skip("database unreachable")
    if not _minio_reachable():
        pytest.skip("MinIO unreachable")
    if not _inference_reachable():
        pytest.skip("inference unreachable")

    asyncio.run(reset_auth_caches())
    from api.main import app

    with TestClient(app) as c:
        yield c
    asyncio.run(reset_auth_caches())
    reset_engine()
    clear_settings_cache()


def _headers(user: str) -> dict[str, str]:
    return {"X-Dev-User": user}


def _policies_collection_id(client: TestClient, user: str) -> str:
    """Resolve the seeded engineering-readable collection by name.

    Indexing ``data[0]`` is not safe: other collections (e.g. the eval corpus's
    restricted "Acme Legal") sort ahead of it and carry a different ACL.
    """
    cols = client.get("/api/v1/collections", headers=_headers(user))
    assert cols.status_code == 200, cols.text
    data = cols.json()["data"]
    match = next((c for c in data if c["name"] == "Acme Policies"), None)
    assert match is not None, f"expected seeded 'Acme Policies' collection, got {data}"
    return str(match["id"])


def test_upload_sync_ingest_and_search(client: TestClient) -> None:
    collection_id = _policies_collection_id(client, "acme-member")

    # Unique per run: the dev database accumulates documents across runs, so a
    # fixed marker can be matched by residue from an earlier (differently scoped)
    # upload and mask or fake an ACL result.
    unique = f"ZXQ{uuid4().hex[:12].upper()} enterprise vacation policy grants twenty days"
    files = {"file": ("vacation.md", unique.encode(), "text/markdown")}
    form = {"collection_id": collection_id, "title": "Vacation Policy", "language": "en"}

    # Uploading is a curator action — a plain member must be refused.
    denied = client.post(
        "/api/v1/documents",
        headers=_headers("acme-member"),
        files={"file": ("vacation.md", unique.encode(), "text/markdown")},
        data=form,
    )
    assert denied.status_code == 403, denied.text

    up = client.post(
        "/api/v1/documents",
        headers=_headers("acme-steward"),
        files=files,
        data=form,
    )
    assert up.status_code == 202, up.text
    body = up.json()
    assert body["dispatch"] in {"sync", "celery"}
    document_id = body["document_id"]

    jobs = client.get(f"/api/v1/documents/{document_id}/jobs", headers=_headers("acme-member"))
    assert jobs.status_code == 200
    job = jobs.json()["data"][0]
    assert job["status"] == "succeeded", job

    search = client.post(
        "/api/v1/search",
        headers=_headers("acme-member"),
        json={"query": f"{unique.split()[0]} vacation", "strategy": "lexical_only", "top_k": 5},
    )
    assert search.status_code == 200, search.text
    hits = search.json()["data"]
    assert hits, "expected at least one hit"
    assert any(unique.split()[0] in h["body"] for h in hits)

    deleted = client.delete(f"/api/v1/documents/{document_id}", headers=_headers("acme-member"))
    assert deleted.status_code == 405
    assert "archive" in deleted.json()["detail"].lower()


def test_acl_different_users_see_different_results(client: TestClient) -> None:
    collection_id = _policies_collection_id(client, "acme-admin")

    marker = f"ACLSPLIT{uuid4().hex[:12].upper()} engineering only secret handbook"
    up = client.post(
        "/api/v1/documents",
        headers=_headers("acme-admin"),
        files={"file": ("eng.md", marker.encode(), "text/markdown")},
        data={"collection_id": collection_id, "title": "Eng Handbook"},
    )
    assert up.status_code == 202, up.text

    jobs = client.get(
        f"/api/v1/documents/{up.json()['document_id']}/jobs",
        headers=_headers("acme-admin"),
    )
    assert jobs.json()["data"][0]["status"] == "succeeded"

    member_search = client.post(
        "/api/v1/search",
        headers=_headers("acme-member"),
        json={"query": marker.split()[0], "strategy": "lexical_only", "top_k": 5},
    )
    viewer_search = client.post(
        "/api/v1/search",
        headers=_headers("acme-viewer"),
        json={"query": marker.split()[0], "strategy": "lexical_only", "top_k": 5},
    )
    assert member_search.status_code == 200
    assert viewer_search.status_code == 200
    member_hits = member_search.json()["data"]
    viewer_hits = viewer_search.json()["data"]
    assert any(marker.split()[0] in h["body"] for h in member_hits)
    assert not any(marker.split()[0] in h["body"] for h in viewer_hits)
