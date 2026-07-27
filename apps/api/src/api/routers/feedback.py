from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.auth import CurrentUser
from api.deps.db import get_db_session
from db.models import Feedback, Query
from domain.errors import NotFoundError

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    query_id: UUID
    rating: Literal["up", "down"]
    reason_code: str | None = Field(default=None, max_length=100)
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    id: UUID
    query_id: UUID
    rating: int


@router.post("", response_model=FeedbackOut, status_code=201)
async def create_feedback(
    body: FeedbackRequest,
    user: CurrentUser,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeedbackOut:
    q = await session.get(Query, body.query_id)
    if q is None or q.tenant_id != user.tenant_id:
        raise NotFoundError("Query not found")
    # Tenant scoping alone let any member rate any other member's queries. Feedback
    # is a judgement about an answer only its asker saw, so it is restricted to the
    # user who made the query. 404 rather than 403 — a caller who may not rate a
    # query has no business learning it exists.
    if q.user_id is not None and q.user_id != user.user_id:
        raise NotFoundError("Query not found")

    rating_int = 1 if body.rating == "up" else -1
    # One vote per user per query. Without this a client could submit unlimited
    # rows for a single answer and skew the quality metric the table exists to
    # produce; re-submitting now updates the existing vote instead.
    existing = await session.scalar(
        select(Feedback).where(
            Feedback.query_id == body.query_id,
            Feedback.user_id == user.user_id,
        )
    )
    if existing is not None:
        existing.rating = rating_int
        existing.reason_code = body.reason_code
        existing.comment = body.comment
        await session.flush()
        # Updated an existing vote rather than creating one — 200, not 201.
        response.status_code = 200
        return FeedbackOut(id=existing.id, query_id=existing.query_id, rating=existing.rating)

    row = Feedback(
        tenant_id=user.tenant_id,
        query_id=body.query_id,
        user_id=user.user_id,
        rating=rating_int,
        reason_code=body.reason_code,
        comment=body.comment,
    )
    session.add(row)
    await session.flush()
    return FeedbackOut(id=row.id, query_id=row.query_id, rating=row.rating)
