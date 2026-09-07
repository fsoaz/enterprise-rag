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


# Clients are created per call rather than cached on the module: these helpers are
# reached from the API (one long-lived loop), the Celery worker (a fresh loop per
# task) and the eval harness, and an AsyncClient cached across event loops raises
# "attached to a different loop". Pooling would need to be owned by the app's
# lifespan to be safe.
def inference_headers() -> dict[str, str]:
    token = os.environ.get("INFERENCE_SERVICE_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def inference_base_url() -> str:
    return os.environ.get("INFERENCE_BASE_URL", "http://localhost:8001").rstrip("/")


async def rerank_documents(
    query: str,
    documents: list[str],
    *,
    top_k: int = DEFAULT_TOP_K_RERANK,
    reranker_model: str | None = None,
    reranker_version: str | None = None,
    inference_endpoint: str | None = None,
) -> list[RerankResult]:
    if not documents:
        return []
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{(inference_endpoint or inference_base_url()).rstrip('/')}/v1/rerank",
                json={"query": query, "documents": documents, "top_k": top_k},
                headers=inference_headers(),
            )
            response.raise_for_status()
            payload = response.json()
            if reranker_model is not None or reranker_version is not None:
                expected_version = reranker_version or ""
                if (
                    payload.get("model") != reranker_model
                    or payload.get("version") != expected_version
                ):
                    raise InferenceUnavailable(
                        "rerank model identity mismatch: "
                        f"requested {reranker_model}@{expected_version}, "
                        f"received {payload.get('model')}@{payload.get('version')}"
                    )
            return [
                RerankResult(index=int(item["index"]), score=float(item["score"]))
                for item in payload["results"]
            ]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise InferenceUnavailable(f"rerank failed: {exc}") from exc
