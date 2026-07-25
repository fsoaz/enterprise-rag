"""Collections CRUD (minimal)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.auth import CuratorUser, CurrentUser
from api.deps.db import get_db_session
from db.models import Collection
from domain.errors import NotFoundError

router = APIRouter(prefix="/collections", tags=["collections"])


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    default_review_interval_days: int = Field(default=90, ge=1, le=3650)


class CollectionOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    default_review_interval_days: int


@router.post("", status_code=201, response_model=CollectionOut)
async def create_collection(
    body: CollectionCreate,
    user: CuratorUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionOut:
    collection = Collection(
        tenant_id=user.tenant_id,
        name=body.name,
        description=body.description,
        default_review_interval_days=body.default_review_interval_days,
    )
    session.add(collection)
    await session.flush()
    return CollectionOut(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        default_review_interval_days=collection.default_review_interval_days,
    )


@router.get("", response_model=dict)
async def list_collections(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    rows = (
        await session.scalars(
            select(Collection)
            .where(Collection.tenant_id == user.tenant_id)
            .order_by(Collection.name)
        )
    ).all()
    return {
        "data": [
            CollectionOut(
                id=c.id,
                name=c.name,
                description=c.description,
                default_review_interval_days=c.default_review_interval_days,
            )
            for c in rows
        ],
        "next_cursor": None,
    }


@router.get("/{collection_id}", response_model=CollectionOut)
async def get_collection(
    collection_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionOut:
    collection = await session.scalar(
        select(Collection).where(
            Collection.id == collection_id,
            Collection.tenant_id == user.tenant_id,
        )
    )
    if collection is None:
        raise NotFoundError(f"No collection {collection_id}")
    return CollectionOut(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        default_review_interval_days=collection.default_review_interval_days,
    )
