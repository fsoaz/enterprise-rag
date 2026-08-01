"""BUG-004: seed remaps drifted tenant primary keys to TENANT_IDS uuid5 values."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from tests.integration_database import integration_database_urls

from db.models import Tenant, User
from db.seed import _remap_tenant_id

pytestmark = pytest.mark.integration


def _migrate_url() -> str | None:
    return integration_database_urls()[1]


async def _reachable(url: str) -> bool:
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except (OSError, TimeoutError, DBAPIError, ProgrammingError):
        return False
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def migrate_engine() -> AsyncIterator[AsyncEngine]:
    url = _migrate_url()
    if not url:
        pytest.skip("DATABASE_URL_MIGRATE / DATABASE_URL not set")
    if not await _reachable(url):
        pytest.skip("database unreachable")
    engine = create_async_engine(url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_remap_tenant_id_preserves_users(migrate_engine: AsyncEngine) -> None:
    old_id = uuid4()
    new_id = uuid4()
    slug = f"remap-{old_id.hex[:8]}"
    user_id = uuid4()
    factory = async_sessionmaker(migrate_engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session, session.begin():
        await session.execute(text("SELECT set_config('app.current_tenant', '', false)"))
        session.add(
            Tenant(
                id=old_id,
                slug=slug,
                name="Remap Fixture",
                status="active",
                settings={},
            )
        )
        await session.flush()
        session.add(
            User(
                id=user_id,
                tenant_id=old_id,
                external_subject=f"user-{user_id.hex[:8]}",
                email=f"{user_id.hex[:8]}@remap.example",
                display_name="Remap User",
                status="active",
            )
        )
        await session.flush()
        await _remap_tenant_id(session, old_id=old_id, new_id=new_id, slug=slug)

        remapped = await session.scalar(select(Tenant).where(Tenant.slug == slug))
        assert remapped is not None
        assert remapped.id == new_id
        assert await session.scalar(select(Tenant).where(Tenant.id == old_id)) is None
        moved = await session.scalar(select(User).where(User.id == user_id))
        assert moved is not None
        assert moved.tenant_id == new_id

        # Cleanup so repeated runs do not accumulate fixture tenants.
        await session.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": new_id})
