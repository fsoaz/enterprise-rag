from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.auth import AuthUser, get_current_user
from db.session import get_session_factory, set_tenant_context


async def get_db_session(
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session with SET LOCAL app.current_tenant from the auth user."""
    factory = get_session_factory()
    async with factory() as session:
        await session.begin()
        await set_tenant_context(session, user.tenant_id)
        try:
            yield session
            if session.in_transaction():
                await session.commit()
        except Exception:
            if session.in_transaction():
                await session.rollback()
            raise
