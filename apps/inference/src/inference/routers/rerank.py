from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1", tags=["rerank"])


class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=100)


class RerankResult(BaseModel):
    index: int
    score: float


class RerankResponse(BaseModel):
    results: list[RerankResult]
    model: str


@router.post("/rerank", response_model=RerankResponse)
async def rerank(body: RerankRequest) -> RerankResponse:
    """Stub: identity rerank — preserves the caller's candidate order.

    Deliberately does NOT invent a ranking signal. An earlier version sorted by
    document length, which actively degraded the fused order it was handed. Until
    real cross-encoder weights land (T-206) the safe behaviour is a no-op that
    passes RRF order through, with monotonically decreasing scores so downstream
    confidence math still sees a sane gradient.
    """
    top = body.documents[: body.top_k]
    results = [RerankResult(index=i, score=1.0 - (i / max(len(top), 1))) for i, _ in enumerate(top)]
    return RerankResponse(results=results, model="identity-rerank-stub")
