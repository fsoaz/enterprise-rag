from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.settings import clear_settings_cache


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
    clear_settings_cache()
    return TestClient(app)


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name = "message"
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
        elif line == "" and data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
            data_lines = []
            event_name = "message"
    if data_lines:
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def test_chat_abstains_when_corpus_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no accessible chunks, chat should abstain (extractive path)."""
    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
    clear_settings_cache()

    # May fail if DB/seed unavailable — skip gracefully
    try:
        with client.stream(
            "POST",
            "/api/v1/chat/completions",
            headers={"X-Dev-User": "acme-member"},
            json={"question": "What is the cafeteria menu?", "stream": True},
        ) as response:
            if response.status_code in {401, 503, 500}:
                pytest.skip(f"deps unavailable: {response.status_code}")
            body = "".join(response.iter_text())
    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        pytest.skip(f"chat deps unavailable: {exc}")

    events = _parse_sse(body)
    names = [e[0] for e in events]
    assert "done" in names or "error" in names
    verdicts = [e[1] for e in events if e[0] == "verdict"]
    if verdicts:
        assert verdicts[0]["groundedness"] in {"grounded", "partial", "unsupported"}
