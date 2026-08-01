"""Collections CRUD (minimal)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.auth import CuratorUser, CurrentUser
from api.deps.db import get_db_session
from api.pagination import apply_descending_cursor, page_limit, page_rows
from db.models import Collection
from domain.errors import ConflictError, NotFoundError
from domain.types import AclEffect, AclPermission, AclResourceType, AclSubjectType
from retrieval.acl import create_acl_entry, resolve_acl

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


class CollectionPage(BaseModel):
    data: list[CollectionOut]
    next_cursor: str | None


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
    try:
        await session.flush()
    except IntegrityError as exc:
        # collections has UNIQUE(tenant_id, name). Unhandled, this surfaced as a
        # generic 500 that gave the caller nothing to act on — and any client that
        # creates-if-missing hits it on its second run.
        await session.rollback()
        raise ConflictError(f"A collection named {body.name!r} already exists") from exc
    # Creator must be able to see and upload into the collection they just made.
    subject_id = str(user.user_id)
    for permission in (AclPermission.READ, AclPermission.WRITE):
        await create_acl_entry(
            session,
            tenant_id=user.tenant_id,
            subject_type=AclSubjectType.USER.value,
            subject_id=subject_id,
            resource_type=AclResourceType.COLLECTION.value,
            resource_id=collection.id,
            permission=permission.value,
            effect=AclEffect.ALLOW.value,
        )
    return CollectionOut(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        default_review_interval_days=collection.default_review_interval_days,
    )


@router.get("", response_model=CollectionPage)
async def list_collections(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = 200,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> CollectionPage:
    limit = page_limit(limit)
    resolution = await resolve_acl(
        session,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        permission=AclPermission.READ,
    )
    stmt = select(Collection).where(Collection.tenant_id == user.tenant_id)
    if not resolution.subjects.is_admin:
        stmt = stmt.where(Collection.id.in_(resolution.allowed_collection_ids))
    stmt = apply_descending_cursor(
        stmt,
        created_column=Collection.created_at,
        id_column=Collection.id,
        cursor=cursor,
    )
    fetched = (
        await session.scalars(
            stmt.order_by(Collection.created_at.desc(), Collection.id.desc()).limit(limit + 1)
        )
    ).all()
    rows, next_cursor = page_rows(
        fetched,
        limit=limit,
        created_at=lambda row: row.created_at,
        item_id=lambda row: row.id,
    )
    return CollectionPage(
        data=[
            CollectionOut(
                id=c.id,
                name=c.name,
                description=c.description,
                default_review_interval_days=c.default_review_interval_days,
            )
            for c in rows
        ],
        next_cursor=next_cursor,
    )


@router.get("/{collection_id}", response_model=CollectionOut)
async def get_collection(
    collection_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionOut:
    resolution = await resolve_acl(
        session,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        permission=AclPermission.READ,
    )
    stmt = select(Collection).where(
        Collection.id == collection_id,
        Collection.tenant_id == user.tenant_id,
    )
    if not resolution.subjects.is_admin:
        stmt = stmt.where(Collection.id.in_(resolution.allowed_collection_ids))
    collection = await session.scalar(stmt)
    if collection is None:
        raise NotFoundError(f"No collection {collection_id}")
    return CollectionOut(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        default_review_interval_days=collection.default_review_interval_days,
    )
