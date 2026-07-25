"""Call inference POST /v1/rerank."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from domain.errors import InferenceUnavailable
from domain.types import DEFAULT_TOP_K_RERANK


@dataclass(frozen=True, slots=True)
class RerankResult:
    index: int
    score: float


async def rerank_documents(
    query: str,
    documents: list[str],
    *,
    top_k: int = DEFAULT_TOP_K_RERANK,
) -> list[RerankResult]:
    if not documents:
        return []
    base = os.environ.get("INFERENCE_BASE_URL", "http://localhost:8001").rstrip("/")
    headers: dict[str, str] = {}
    token = os.environ.get("INFERENCE_SERVICE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base}/v1/rerank",
                json={"query": query, "documents": documents, "top_k": top_k},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
            return [
                RerankResult(index=int(item["index"]), score=float(item["score"]))
                for item in payload["results"]
            ]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise InferenceUnavailable(f"rerank failed: {exc}") from exc
