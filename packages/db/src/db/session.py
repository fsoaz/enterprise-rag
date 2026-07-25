from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import Connection, event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

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


_TENANT_INFO_KEY = "app_current_tenant"
_SET_TENANT_SQL = text("SELECT set_config('app.current_tenant', :tid, true)")


@event.listens_for(Session, "after_begin")
def _reapply_tenant_context(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    """Re-establish the tenant GUC whenever a new transaction begins.

    ``set_config(..., is_local => true)`` is scoped to the transaction, so any
    commit clears it. Code that committed mid-request and kept using the session
    then hit RLS with an empty setting and failed with
    ``invalid input syntax for type uuid: ""`` — including error handlers, which
    turned a recoverable fault into an opaque 500.

    Binding it to ``after_begin`` makes the context follow the session instead of
    a single transaction, so committing mid-request is safe. Kept transaction-local
    (never session-level) so a pooled connection cannot carry one tenant's context
    into the next checkout.
    """
    tenant_id = session.info.get(_TENANT_INFO_KEY)
    if tenant_id is None:
        return
    connection.execute(_SET_TENANT_SQL, {"tid": str(tenant_id)})


async def set_tenant_context(session: AsyncSession, tenant_id: UUID) -> None:
    """SET LOCAL app.current_tenant for this session's transactions (RLS)."""
    session.sync_session.info[_TENANT_INFO_KEY] = tenant_id
    await session.execute(_SET_TENANT_SQL, {"tid": str(tenant_id)})


def clear_tenant_context(session: AsyncSession) -> None:
    """Forget the session's tenant so later transactions do not re-apply it."""
    session.sync_session.info.pop(_TENANT_INFO_KEY, None)


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
