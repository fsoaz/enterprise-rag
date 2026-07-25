"""Search API — retrieval strategies under ACL pre-filter."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.auth import CurrentUser
from api.deps.db import get_db_session
from domain.types import DEFAULT_TOP_K_RERANK, RetrievalStrategy
from retrieval.pipeline import retrieve

router = APIRouter(prefix="/search", tags=["search"])

StrategyLiteral = Literal["dense_only", "lexical_only", "hybrid_rrf", "hybrid_rerank"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    strategy: StrategyLiteral = "hybrid_rrf"
    top_k: int = Field(default=DEFAULT_TOP_K_RERANK, ge=1, le=50)


class SearchHitOut(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    body: str
    score: float


class SearchResponse(BaseModel):
    data: list[SearchHitOut]
    strategy: str
    acl_version: int


@router.post("", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SearchResponse:
    result = await retrieve(
        session,
        tenant_id=user.tenant_id,
        user_id=user.id,
        query=body.query,
        strategy=RetrievalStrategy(body.strategy),
        top_k=body.top_k,
    )
    return SearchResponse(
        data=[
            SearchHitOut(
                chunk_id=h.chunk_id,
                document_id=h.document_id,
                document_version_id=h.document_version_id,
                body=h.body,
                score=h.score,
            )
            for h in result.hits
        ],
        strategy=result.strategy,
        acl_version=result.acl_version,
    )
