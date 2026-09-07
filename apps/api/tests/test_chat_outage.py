"""The real retrieval transport must fail before any response stream opens."""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest

from api.deps.auth import AuthUser, get_current_user
from api.deps.db import get_db_session
from api.main import app
from api.routers import chat
from retrieval import pipeline


@pytest.mark.parametrize("stream", [False, True])
async def test_inference_transport_outage_returns_problem(
    monkeypatch: pytest.MonkeyPatch, stream: bool
) -> None:
    user = AuthUser(uuid4(), uuid4(), "test", "test@example.test", ("viewer",), ())
    generation = Mock(side_effect=AssertionError("generation must not start"))
    transport = AsyncMock(side_effect=httpx.ConnectError("inference unavailable"))
    acl = AsyncMock()
    monkeypatch.setattr(chat, "enforce_rate_limit", AsyncMock())
    monkeypatch.setattr(chat, "assert_within_budget", AsyncMock())
    monkeypatch.setattr(chat, "run_chat", generation)
    monkeypatch.setattr(pipeline, "resolve_acl", acl)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", transport)
    previous = app.dependency_overrides.copy()

    async def current_user() -> AuthUser:
        return user

    async def session() -> Mock:
        return Mock()

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db_session] = session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/chat/completions",
                json={"question": "What is the policy?", "stream": stream},
            )
        assert response.status_code == 503, response.text
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["type"].endswith("/retrieval-unavailable")
        assert response.json()["status"] == 503
        acl.assert_awaited_once()
        transport.assert_awaited_once()
        assert transport.call_args.args[0].url.path == "/v1/embed"
        generation.assert_not_called()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
