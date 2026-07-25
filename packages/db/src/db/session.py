from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_database_url() -> str:
    """Read DATABASE_URL at call time (no import-time side effects)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        msg = "DATABASE_URL is not set"
        raise RuntimeError(msg)
    return url


def create_engine(url: str | None = None, *, echo: bool = False) -> AsyncEngine:
    return create_async_engine(
        url or get_database_url(),
        echo=echo,
        pool_pre_ping=True,
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def set_tenant_context(session: AsyncSession, tenant_id: UUID) -> None:
    """SET LOCAL app.current_tenant for the current transaction (RLS)."""
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": str(tenant_id)},
    )


@asynccontextmanager
async def tenant_session(tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    """Yield a session with transaction-local tenant context set."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_context(session, tenant_id)
        yield session


def reset_engine() -> None:
    """Drop cached engine/factory — used by tests."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
