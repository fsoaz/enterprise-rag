from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.auth import CurrentUser
from api.deps.db import get_db_session
from db.models import Feedback, Query
from domain.errors import NotFoundError

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    query_id: UUID
    rating: Literal["up", "down"]
    reason_code: str | None = None
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    id: UUID
    query_id: UUID
    rating: int


@router.post("", response_model=FeedbackOut, status_code=201)
async def create_feedback(
    body: FeedbackRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeedbackOut:
    q = await session.get(Query, body.query_id)
    if q is None or q.tenant_id != user.tenant_id:
        raise NotFoundError("Query not found")
    rating_int = 1 if body.rating == "up" else -1
    row = Feedback(
        tenant_id=user.tenant_id,
        query_id=body.query_id,
        user_id=user.id,
        rating=rating_int,
        reason_code=body.reason_code,
        comment=body.comment,
    )
    session.add(row)
    await session.flush()
    return FeedbackOut(id=row.id, query_id=row.query_id, rating=row.rating)
