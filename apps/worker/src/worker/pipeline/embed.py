"""Call inference POST /v1/embed with mode=passage."""

from __future__ import annotations

import os
from typing import Any

import httpx

from domain.errors import InferenceUnavailable


def _inference_base_url() -> str:
    return os.environ.get("INFERENCE_BASE_URL", "http://localhost:8001").rstrip("/")


def _service_token() -> str | None:
    return os.environ.get("INFERENCE_SERVICE_TOKEN")


async def embed_passages(
    texts: list[str],
    *,
    client: httpx.AsyncClient | None = None,
) -> list[list[float]]:
    if not texts:
        return []
    headers: dict[str, str] = {}
    token = _service_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload: dict[str, Any] = {"texts": texts, "mode": "passage"}
    url = f"{_inference_base_url()}/v1/embed"

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=60.0)
    try:
        response = await http.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        vectors = data.get("vectors")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise InferenceUnavailable("embed response missing vectors")
        return vectors
    except httpx.HTTPError as exc:
        raise InferenceUnavailable(f"embed request failed: {exc}") from exc
    finally:
        if owns_client:
            await http.aclose()


def embedding_model_meta() -> tuple[str, str]:
    from domain.embeddings import embedding_model_meta as _meta

    return _meta()
