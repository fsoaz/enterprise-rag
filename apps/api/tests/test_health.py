from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


def test_health() -> None:
    """Liveness must never depend on Postgres or Redis being reachable."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_reports_each_dependency() -> None:
    """Readiness reports per-dependency results and 503s when one is down.

    Deliberately not asserting ``ready`` here: the point of the endpoint is that it
    reflects real dependency state, so the answer depends on whether infra is up.
    The contract under test is the shape and the status-code coupling.
    """
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code in {200, 503}
    body = response.json()
    assert set(body["checks"]) == {"database", "redis", "inference"}
    if all(body["checks"].values()):
        assert response.status_code == 200
        assert body["status"] == "ready"
    else:
        assert response.status_code == 503
        assert body["status"] == "degraded"


@pytest.mark.integration
def test_ready_is_ready_with_infra_up() -> None:
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready"
