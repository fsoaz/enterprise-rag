from __future__ import annotations

from types import SimpleNamespace

import pytest

from domain.errors import InferenceUnavailable
from retrieval import dense, rerank


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def post(self, *args: object, **kwargs: object) -> _Response:
        del args, kwargs
        return self.response


@pytest.mark.asyncio
async def test_embed_rejects_response_for_wrong_requested_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kwargs: _Client(
            _Response({"vectors": [[1.0]], "model": "wrong", "version": "v0"})
        ),
    )
    with pytest.raises(InferenceUnavailable, match="identity mismatch"):
        await dense.embed_query(
            SimpleNamespace(),
            "question",
            embedding_model_name="expected",
            embedding_model_version="v1",
            inference_endpoint="http://inference-a",
        )


@pytest.mark.asyncio
async def test_rerank_uses_configured_endpoint_and_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Client(_Client):
        async def post(self, url: str, **kwargs: object) -> _Response:
            calls.append(url)
            del kwargs
            return _Response(
                {"results": [{"index": 0, "score": 1.0}], "model": "reranker", "version": "v2"}
            )

    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: Client(_Response({})))
    result = await rerank.rerank_documents(
        "question",
        ["document"],
        reranker_model="reranker",
        reranker_version="v2",
        inference_endpoint="http://inference-b",
    )
    assert result[0].index == 0
    assert calls == ["http://inference-b/v1/rerank"]
