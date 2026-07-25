"""ACL entry management — writes bump acl_versions in the same transaction."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.auth import AclAdminUser
from api.deps.db import get_db_session
from db.models import AclEntry
from retrieval.acl import create_acl_entry

router = APIRouter(prefix="/acl", tags=["acl"])

SubjectType = Literal["user", "group", "role"]
ResourceType = Literal["collection", "document"]
Permission = Literal["read", "write", "manage"]
Effect = Literal["allow", "deny"]


class AclEntryCreate(BaseModel):
    subject_type: SubjectType
    subject_id: str = Field(min_length=1)
    resource_type: ResourceType
    resource_id: UUID
    permission: Permission = "read"
    effect: Effect = "allow"


class AclEntryOut(BaseModel):
    id: UUID
    subject_type: str
    subject_id: str
    resource_type: str
    resource_id: UUID
    permission: str
    effect: str


@router.post("/entries", status_code=201, response_model=AclEntryOut)
async def post_acl_entry(
    body: AclEntryCreate,
    user: AclAdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AclEntryOut:
    entry = await create_acl_entry(
        session,
        tenant_id=user.tenant_id,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        permission=body.permission,
        effect=body.effect,
    )
    return AclEntryOut(
        id=entry.id,
        subject_type=entry.subject_type,
        subject_id=entry.subject_id,
        resource_type=entry.resource_type,
        resource_id=entry.resource_id,
        permission=entry.permission,
        effect=entry.effect,
    )


@router.get("/entries", response_model=dict)
async def list_acl_entries(
    user: AclAdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    resource_type: ResourceType | None = None,
    resource_id: UUID | None = None,
) -> dict[str, object]:
    stmt = select(AclEntry).where(AclEntry.tenant_id == user.tenant_id)
    if resource_type is not None:
        stmt = stmt.where(AclEntry.resource_type == resource_type)
    if resource_id is not None:
        stmt = stmt.where(AclEntry.resource_id == resource_id)
    rows = (await session.scalars(stmt.order_by(AclEntry.created_at.desc()).limit(200))).all()
    return {
        "data": [
            AclEntryOut(
                id=e.id,
                subject_type=e.subject_type,
                subject_id=e.subject_id,
                resource_type=e.resource_type,
                resource_id=e.resource_id,
                permission=e.permission,
                effect=e.effect,
            )
            for e in rows
        ],
        "next_cursor": None,
    }
