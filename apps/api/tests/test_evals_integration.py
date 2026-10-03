"""End-to-end evaluation API checks against the disposable database."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from tests.integration_database import integration_database_urls

from api.deps.auth import AuthUser, get_current_user, reset_auth_caches
from api.deps.db import get_db_session
from api.settings import clear_settings_cache
from db.session import reset_engine

pytestmark = pytest.mark.integration


async def _reachable(url: str) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    app_url, migrate_url = integration_database_urls()
    if not asyncio.run(_reachable(app_url)):
        pytest.skip("database unreachable")
    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
    monkeypatch.setenv("DATABASE_URL", app_url)
    monkeypatch.setenv("DATABASE_URL_MIGRATE", migrate_url)
    clear_settings_cache()
    reset_engine()
    asyncio.run(reset_auth_caches())
    from api.main import app

    with TestClient(app) as value:
        yield value
    asyncio.run(reset_auth_caches())
    reset_engine()
    clear_settings_cache()


async def _purge(names: list[str]) -> None:
    _, migrate_url = integration_database_urls()
    engine = create_async_engine(migrate_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SELECT set_config('app.current_tenant', '', false)"))
            await connection.execute(
                text("DELETE FROM eval_datasets WHERE name = ANY(CAST(:names AS text[]))"),
                {"names": names},
            )
    finally:
        await engine.dispose()


def _complete_runs(run_ids: list[str], dataset_id: str, values: list[float]) -> None:
    _, migrate_url = integration_database_urls()
    with (
        psycopg.connect(migrate_url.replace("+asyncpg", "")) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT id FROM eval_items WHERE dataset_id = %s ORDER BY id", (dataset_id,))
        item_ids = [row[0] for row in cursor.fetchall()]
        for run_id, value in zip(run_ids, values, strict=True):
            cursor.execute(
                "UPDATE eval_runs SET params = params || %s::jsonb, "
                "finished_at = now() WHERE id = %s",
                (json.dumps({"status": "complete", "progress": 100}), run_id),
            )
            for item_id in item_ids:
                cursor.execute(
                    """
                    INSERT INTO eval_results (tenant_id, run_id, item_id, metrics)
                    SELECT tenant_id, %s, %s, %s::jsonb FROM eval_runs WHERE id = %s
                    """,
                    (run_id, item_id, json.dumps({"recall@10": value}), run_id),
                )


def _mark_run_complete(run_id: str) -> None:
    _, migrate_url = integration_database_urls()
    with (
        psycopg.connect(migrate_url.replace("+asyncpg", "")) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE eval_runs SET params = params || %s::jsonb, finished_at = now() WHERE id = %s",
            (json.dumps({"status": "complete", "progress": 100}), run_id),
        )


def test_canonical_comparison_matrix_and_conflict_coverage(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("api.routers.evals._dispatch_run", lambda run_id: None)
    name = f"t406-{uuid4().hex}"
    headers = {"X-Dev-User": "acme-admin"}
    try:
        dataset = client.post(
            "/api/v1/evals/datasets",
            headers=headers,
            json={
                "name": name,
                "version": "1",
                "items": [
                    {"id": "en-1", "slice": "factual_en", "question": "q1"},
                    {"id": "pt-1", "slice": "factual_pt", "question": "q2"},
                ],
            },
        )
        assert dataset.status_code == 201, dataset.text
        dataset_id = dataset.json()["id"]
        run_ids: list[str] = []
        for strategy in ("hybrid_rrf", "dense_only"):
            run = client.post(
                "/api/v1/evals/runs",
                headers=headers,
                json={
                    "dataset_id": dataset_id,
                    "strategy": strategy,
                    "embedding_model": "BAAI/bge-m3",
                    "generator_model": "extractive-fallback",
                    "params": {"embedding_model_version": "stub-v0"},
                },
            )
            assert run.status_code == 202, run.text
            run_ids.append(run.json()["id"])
        _complete_runs(run_ids, dataset_id, [0.5, 0.8])
        response = client.get(
            "/api/v1/evals/runs/compare?ids=" + ",".join(run_ids), headers=headers
        )
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["baseline_run_id"] == run_ids[0]
        assert set(report["by_slice"]) == {"factual_en", "factual_pt"}
        assert report["overall"]["recall@10"][run_ids[1]]["delta"] == 0.30000000000000004
        assert report["coverage"]["overall"][run_ids[1]]["result_count"] == 2

        comparison_url = "/api/v1/evals/runs/compare?ids=" + ",".join(run_ids)
        assert client.get(comparison_url, headers={"X-Dev-User": "acme-member"}).status_code == 403
        assert client.get(comparison_url, headers={"X-Dev-User": "globex-admin"}).status_code == 404
        for invalid_ids, expected in [
            (run_ids[0], 409),
            (f"{run_ids[0]},{run_ids[0]}", 409),
            ("invalid,uuid", 409),
            (f"{run_ids[0]},{uuid4()}", 404),
        ]:
            invalid = client.get("/api/v1/evals/runs/compare?ids=" + invalid_ids, headers=headers)
            assert invalid.status_code == expected, invalid.text

        incomplete = client.post(
            "/api/v1/evals/runs",
            headers=headers,
            json={
                "dataset_id": dataset_id,
                "strategy": "lexical_only",
                "embedding_model": "BAAI/bge-m3",
                "generator_model": "extractive-fallback",
            },
        )
        conflict = client.get(
            "/api/v1/evals/runs/compare?ids=" + ",".join((*run_ids, incomplete.json()["id"])),
            headers=headers,
        )
        assert conflict.status_code == 409
        assert "incomplete" in conflict.json()["detail"]
        assert conflict.headers["content-type"].startswith("application/problem+json")

        missing = client.post(
            "/api/v1/evals/runs",
            headers=headers,
            json={
                "dataset_id": dataset_id,
                "strategy": "lexical_only",
                "embedding_model": "BAAI/bge-m3",
                "generator_model": "extractive-fallback",
            },
        )
        _mark_run_complete(missing.json()["id"])
        missing_conflict = client.get(
            "/api/v1/evals/runs/compare?ids=" + ",".join((run_ids[0], missing.json()["id"])),
            headers=headers,
        )
        assert missing_conflict.status_code == 409
        assert "missing or duplicate results" in missing_conflict.json()["detail"]
    finally:
        asyncio.run(_purge([name]))


def test_eval_registration_runs_results_comparison_and_isolation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("api.routers.evals._dispatch_run", lambda run_id: None)
    name = f"t405-{uuid4().hex}"
    other_name = f"t405-other-{uuid4().hex}"
    try:
        body = {
            "name": name,
            "version": "1",
            "dataset_slice": "unanswerable",
            "items": [
                {
                    "id": "ua-001",
                    "question": "What is not in the corpus?",
                    "expected_answer_facts": [],
                    "language": "en",
                    "should_abstain": True,
                },
                {
                    "id": "ua-002",
                    "question": "What else is not in the corpus?",
                    "expected_answer_facts": [],
                    "language": "en",
                    "should_abstain": True,
                },
            ],
        }
        created = client.post(
            "/api/v1/evals/datasets", headers={"X-Dev-User": "acme-admin"}, json=body
        )
        assert created.status_code == 201, created.text
        dataset_id = created.json()["id"]
        assert created.json()["content_sha256"]

        second_dataset = dict(body)
        second_dataset["name"] = other_name
        second_dataset["items"] = [dict(body["items"][0])]
        second_created = client.post(
            "/api/v1/evals/datasets",
            headers={"X-Dev-User": "acme-admin"},
            json=second_dataset,
        )
        assert second_created.status_code == 201, second_created.text

        duplicate = client.post(
            "/api/v1/evals/datasets", headers={"X-Dev-User": "acme-admin"}, json=body
        )
        assert duplicate.status_code == 409
        assert duplicate.headers["content-type"].startswith("application/problem+json")

        page = client.get("/api/v1/evals/datasets?limit=1", headers={"X-Dev-User": "acme-admin"})
        assert page.status_code == 200
        assert page.json()["next_cursor"]
        items = client.get(
            f"/api/v1/evals/datasets/{dataset_id}/items?limit=1",
            headers={"X-Dev-User": "acme-admin"},
        )
        assert items.status_code == 200
        assert items.json()["data"][0]["external_id"] in {"ua-001", "ua-002"}
        assert items.json()["next_cursor"]

        first = client.post(
            "/api/v1/evals/runs",
            headers={"X-Dev-User": "acme-admin"},
            json={
                "dataset_id": dataset_id,
                "strategy": "lexical_only",
                "embedding_model": "stub-v0",
                "generator_model": "extractive-fallback",
            },
        )
        assert first.status_code == 202
        first_id = first.json()["id"]
        assert (
            client.get(
                f"/api/v1/evals/runs/{first_id}", headers={"X-Dev-User": "acme-admin"}
            ).json()["status"]
            == "queued"
        )

        other_run = client.post(
            "/api/v1/evals/runs",
            headers={"X-Dev-User": "acme-admin"},
            json={
                "dataset_id": second_created.json()["id"],
                "strategy": "dense_only",
                "embedding_model": "stub-v0",
                "generator_model": "extractive-fallback",
            },
        )
        assert other_run.status_code == 202, other_run.text
        incompatible = client.get(
            f"/api/v1/evals/runs/compare?ids={first_id},{other_run.json()['id']}",
            headers={"X-Dev-User": "acme-admin"},
        )
        assert incompatible.status_code == 409, incompatible.text
        assert "incompatible datasets" in incompatible.json()["detail"]

        hidden = client.get(
            f"/api/v1/evals/datasets/{dataset_id}/items",
            headers={"X-Dev-User": "globex-admin"},
        )
        assert hidden.status_code == 404
        denied = client.get(f"/api/v1/evals/runs/{first_id}", headers={"X-Dev-User": "acme-member"})
        assert denied.status_code == 403
    finally:
        asyncio.run(_purge([name, other_name]))


def test_eval_validation_is_problem_response(client: TestClient) -> None:
    response = client.post(
        "/api/v1/evals/datasets",
        headers={"X-Dev-User": "acme-admin"},
        json={"name": "invalid", "version": "1", "items": [{"question": "x", "extra": 1}]},
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"].endswith("/validation-failed")
    assert response.json()["request_id"]


@pytest.mark.parametrize("publication_fails", [False, True])
def test_create_run__dispatch__sees_committed_run_and_persists_outcome(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, publication_fails: bool
) -> None:
    name = f"t411-{uuid4().hex}"
    headers = {"X-Dev-User": "acme-admin"}
    app_url, migrate_url = integration_database_urls()
    with psycopg.connect(migrate_url.replace("+asyncpg", "")) as connection:
        tenant_id = connection.execute("SELECT id FROM tenants WHERE slug = 'acme'").fetchone()[0]
        other_tenant_id = connection.execute(
            "SELECT id FROM tenants WHERE slug = 'globex'"
        ).fetchone()[0]

    def read_params(run_id: UUID, tenant: UUID) -> dict[str, object] | None:
        # Each read opens a separate connection as rag_app, with tenant RLS active.
        with psycopg.connect(app_url.replace("+asyncpg", "")) as connection:
            connection.execute("SELECT set_config('app.current_tenant', %s, true)", (str(tenant),))
            row = connection.execute(
                "SELECT params FROM eval_runs WHERE id = %s", (run_id,)
            ).fetchone()
            return row[0] if row else None

    observed = []

    def dispatch(run_id: UUID) -> None:
        observed.append(read_params(run_id, tenant_id))
        if publication_fails:
            raise RuntimeError("publication unavailable")

    monkeypatch.setattr("api.routers.evals._dispatch_run", dispatch)
    try:
        dataset = client.post(
            "/api/v1/evals/datasets",
            headers=headers,
            json={
                "name": name,
                "version": "1",
                "items": [{"question": "q"}],
            },
        )
        assert dataset.status_code == 201, dataset.text
        response = client.post(
            "/api/v1/evals/runs",
            headers=headers,
            json={
                "dataset_id": dataset.json()["id"],
                "strategy": "hybrid_rrf",
                "embedding_model": "stub-v0",
                "generator_model": "extractive-fallback",
            },
        )
        assert response.status_code == 202, response.text
        assert len(observed) == 1
        assert observed[0] is not None
        assert observed[0]["status"] == "queued"
        run_id = UUID(response.json()["id"])
        params = read_params(run_id, tenant_id)
        assert params is not None
        expected_status = "failed" if publication_fails else "queued"
        assert params["status"] == expected_status
        assert read_params(run_id, other_tenant_id) is None
        lookup = client.get(f"/api/v1/evals/runs/{run_id}", headers=headers)
        assert lookup.status_code == 200, lookup.text
        assert lookup.json()["status"] == response.json()["status"] == expected_status
        if publication_fails:
            assert params["error"] == response.json()["error"] == "publication unavailable"
    finally:
        asyncio.run(_purge([name]))


def test_register_dataset__before_dependency_cleanup__visible_to_other_connections(
    client: TestClient,
) -> None:
    from api.main import app

    name = f"t413-{uuid4().hex}"
    observed = False

    async def observed_session(
        user: Annotated[AuthUser, Depends(get_current_user)],
    ) -> AsyncIterator[AsyncSession]:
        nonlocal observed
        async for session in get_db_session(user):
            yield session
            # Check before get_db_session resumes and performs its cleanup commit.
            app_url, _ = integration_database_urls()
            with (
                psycopg.connect(app_url.replace("+asyncpg", "")) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "SELECT set_config('app.current_tenant', %s, true)",
                    (str(user.tenant_id),),
                )
                cursor.execute(
                    "SELECT count(*) FROM eval_items i JOIN eval_datasets d "
                    "ON d.id = i.dataset_id WHERE d.name = %s",
                    (name,),
                )
                assert cursor.fetchone() == (1,)
                observed = True

    app.dependency_overrides[get_db_session] = observed_session
    try:
        created = client.post(
            "/api/v1/evals/datasets",
            headers={"X-Dev-User": "acme-admin"},
            json={
                "name": name,
                "version": "1",
                "items": [{"question": "Unknown?", "should_abstain": True}],
            },
        )
        assert created.status_code == 201, created.text
        assert observed
        app.dependency_overrides.pop(get_db_session)
        hidden = client.get(
            f"/api/v1/evals/datasets/{created.json()['id']}/items",
            headers={"X-Dev-User": "globex-admin"},
        )
        assert hidden.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        asyncio.run(_purge([name]))
