from __future__ import annotations

import math
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from inference.backend import BgeBackend, reset_backend
from inference.main import app


@pytest.fixture(autouse=True)
def _no_ambient_token(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Default to the unauthenticated configuration.

    A developer .env sets INFERENCE_SERVICE_TOKEN; without this the token would
    leak into every test and the behavioural assertions below would depend on the
    machine they run on. Tests that care about auth set the variable themselves.
    """
    monkeypatch.delenv("INFERENCE_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv("INFERENCE_BACKEND", "stub")
    reset_backend()
    yield
    reset_backend()


def test_embed_returns_1024_dim() -> None:
    client = TestClient(app)
    response = client.post("/v1/embed", json={"texts": ["hello"], "mode": "query"})
    assert response.status_code == 200
    data = response.json()
    assert data["dim"] == 1024
    assert len(data["vectors"]) == 1
    assert len(data["vectors"][0]) == 1024


def test_embed_is_never_the_zero_vector() -> None:
    """pgvector cosine distance is NaN against a zero vector — dense search breaks."""
    client = TestClient(app)
    response = client.post("/v1/embed", json={"texts": ["hello", "world"], "mode": "passage"})
    assert response.status_code == 200
    for vector in response.json()["vectors"]:
        assert any(component != 0.0 for component in vector)
        norm = math.sqrt(sum(c * c for c in vector))
        assert norm == pytest.approx(1.0, abs=1e-6)


def test_embed_is_deterministic() -> None:
    client = TestClient(app)
    first = client.post("/v1/embed", json={"texts": ["stable"], "mode": "passage"}).json()
    second = client.post("/v1/embed", json={"texts": ["stable"], "mode": "passage"}).json()
    assert first["vectors"] == second["vectors"]


def test_rerank_preserves_candidate_order() -> None:
    """The stub must not invent a ranking signal — it passes fused order through."""
    client = TestClient(app)
    response = client.post(
        "/v1/rerank",
        json={"query": "policy", "documents": ["a", "longer document here", "b"], "top_k": 2},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 2
    assert [r["index"] for r in data["results"]] == [0, 1]
    assert data["results"][0]["score"] >= data["results"][1]["score"]


def test_bge_backend_uses_normalized_embeddings_and_cross_encoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the production adapter without downloading multi-gigabyte weights."""

    class FakeArray:
        def __init__(self, value: Any) -> None:
            self.value = value

        def tolist(self) -> Any:
            return self.value

    class FakeEmbedder:
        kwargs: dict[str, Any]
        encode_kwargs: dict[str, Any]

        def __init__(self, _model: str, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def encode(self, texts: list[str], **kwargs: Any) -> FakeArray:
            self.encode_kwargs = kwargs
            return FakeArray([[1.0] + [0.0] * 1023 for _ in texts])

    class FakeReranker:
        def __init__(self, _model: str, **_kwargs: Any) -> None:
            pass

        def predict(self, pairs: list[tuple[str, str]], **_kwargs: Any) -> FakeArray:
            return FakeArray([0.1 if document == "weak" else 0.9 for _, document in pairs])

    fake_module = SimpleNamespace(SentenceTransformer=FakeEmbedder, CrossEncoder=FakeReranker)
    monkeypatch.setattr(
        "inference.backend.importlib.import_module",
        lambda name: fake_module if name == "sentence_transformers" else None,
    )

    backend = BgeBackend()
    vectors = backend.embed(["olá", "hello"], mode="query")
    assert len(vectors) == 2
    assert len(vectors[0]) == 1024
    assert backend._embedder.encode_kwargs["normalize_embeddings"] is True
    assert backend.rerank("policy", ["weak", "strong"]) == [0.1, 0.9]


def test_service_token_is_enforced_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INFERENCE_SERVICE_TOKEN", "s3cret")
    client = TestClient(app)
    payload = {"texts": ["hello"], "mode": "query"}

    assert client.post("/v1/embed", json=payload).status_code == 401
    assert (
        client.post(
            "/v1/embed", json=payload, headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/v1/embed", json=payload, headers={"Authorization": "Bearer s3cret"}
        ).status_code
        == 200
    )


def test_service_token_open_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INFERENCE_SERVICE_TOKEN", raising=False)
    client = TestClient(app)
    response = client.post("/v1/embed", json={"texts": ["hello"], "mode": "query"})
    assert response.status_code == 200
