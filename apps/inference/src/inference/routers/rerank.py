from __future__ import annotations

import anyio
from fastapi import APIRouter
from pydantic import BaseModel, Field

from inference.backend import get_backend

router = APIRouter(prefix="/v1", tags=["rerank"])


class RerankRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    documents: list[str] = Field(min_length=1, max_length=100)
    top_k: int = Field(default=8, ge=1, le=100)


class RerankResult(BaseModel):
    index: int
    score: float


class RerankResponse(BaseModel):
    results: list[RerankResult]
    model: str


@router.post("/rerank", response_model=RerankResponse)
async def rerank(body: RerankRequest) -> RerankResponse:
    backend = get_backend()
    scores = await anyio.to_thread.run_sync(backend.rerank, body.query, body.documents)
    ranked = sorted(enumerate(scores), key=lambda item: (-item[1], item[0]))[: body.top_k]
    results = [RerankResult(index=index, score=score) for index, score in ranked]
    return RerankResponse(results=results, model=backend.rerank_model)
