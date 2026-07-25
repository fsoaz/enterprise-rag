from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.auth import AuthUser, get_current_user
from api.deps.db import get_db_session
from api.settings import get_settings
from db.models import User
from domain.errors import NotFoundError

router = APIRouter(prefix="/api/v1", tags=["identity"])


class MeResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    external_subject: str
    email: str
    roles: list[str]
    groups: list[str]


class VisibleUser(BaseModel):
    external_subject: str
    email: str
    tenant_id: UUID


@router.get("/me", response_model=MeResponse)
async def me(user: Annotated[AuthUser, Depends(get_current_user)]) -> MeResponse:
    return MeResponse(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        external_subject=user.external_subject,
        email=user.email,
        roles=list(user.roles),
        groups=list(user.groups),
    )


@router.get("/debug/users", response_model=list[VisibleUser])
async def debug_visible_users(
    _user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[VisibleUser]:
    """List users visible under the caller's RLS tenant context (DEV_AUTH_BYPASS only)."""
    if not get_settings().dev_auth_bypass:
        raise NotFoundError()
    rows = await session.scalars(select(User).order_by(User.external_subject))
    return [
        VisibleUser(
            external_subject=row.external_subject,
            email=row.email,
            tenant_id=row.tenant_id,
        )
        for row in rows.all()
    ]
