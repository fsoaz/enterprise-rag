"""Tenant isolation via Postgres RLS (architecture § 4.2 / testing.md)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration_database import integration_database_urls

pytestmark = pytest.mark.integration


def _app_url() -> str | None:
    return integration_database_urls()[0]


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


@pytest_asyncio.fixture
async def app_engine() -> AsyncIterator[AsyncEngine]:
    url = _app_url()
    if not url:
        pytest.skip("DATABASE_URL not set")
    if not await _reachable(url):
        pytest.skip("database unreachable")
    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_rls_blocks_cross_tenant_raw_select(
    migrate_engine: AsyncEngine,
    app_engine: AsyncEngine,
) -> None:
    """Insert two tenants; with app.current_tenant=A, raw SELECT must not see B."""
    tenant_a = uuid4()
    tenant_b = uuid4()
    user_a = uuid4()
    user_b = uuid4()

    async with migrate_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO tenants (id, slug, name, status, settings)
                VALUES
                  (:a, :sa, 'Tenant A', 'active', '{}'::jsonb),
                  (:b, :sb, 'Tenant B', 'active', '{}'::jsonb)
                ON CONFLICT (slug) DO NOTHING
                """
            ),
            {
                "a": tenant_a,
                "b": tenant_b,
                "sa": f"rls-a-{tenant_a.hex[:8]}",
                "sb": f"rls-b-{tenant_b.hex[:8]}",
            },
        )
        await conn.execute(
            text(
                """
                INSERT INTO users (
                  id, tenant_id, external_subject, email, display_name, status
                ) VALUES
                  (:ua, :a, :suba, :ea, 'User A', 'active'),
                  (:ub, :b, :subb, :eb, 'User B', 'active')
                """
            ),
            {
                "ua": user_a,
                "ub": user_b,
                "a": tenant_a,
                "b": tenant_b,
                "suba": f"sub-a-{user_a.hex[:8]}",
                "subb": f"sub-b-{user_b.hex[:8]}",
                "ea": f"a-{user_a.hex[:8]}@example.com",
                "eb": f"b-{user_b.hex[:8]}@example.com",
            },
        )

    async with app_engine.connect() as conn:
        await conn.execute(text("BEGIN"))
        await conn.execute(
            text("SELECT set_config('app.current_tenant', :tid, true)"),
            {"tid": str(tenant_a)},
        )
        # Deliberately no tenant_id WHERE — RLS is the only filter.
        rows = (await conn.execute(text("SELECT id, tenant_id FROM users"))).fetchall()
        await conn.execute(text("COMMIT"))

    seen_tenants = {row.tenant_id for row in rows}
    assert tenant_a in seen_tenants
    assert tenant_b not in seen_tenants
    assert all(row.tenant_id == tenant_a for row in rows)

    async with migrate_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM users WHERE id = :a OR id = :b"),
            {"a": user_a, "b": user_b},
        )
        await conn.execute(
            text("DELETE FROM tenants WHERE id = :a OR id = :b"),
            {"a": tenant_a, "b": tenant_b},
        )


@pytest.mark.asyncio
async def test_rls_blocks_insert_for_wrong_tenant(app_engine: AsyncEngine) -> None:
    """WITH CHECK must reject inserting a row for a different tenant."""
    tenant_a = uuid4()
    other = uuid4()

    async with app_engine.connect() as conn:
        await conn.execute(text("BEGIN"))
        await conn.execute(
            text("SELECT set_config('app.current_tenant', :tid, true)"),
            {"tid": str(tenant_a)},
        )
        with pytest.raises(DBAPIError):
            await conn.execute(
                text(
                    """
                    INSERT INTO groups (id, tenant_id, name)
                    VALUES (:id, :tid, 'should-fail')
                    """
                ),
                {"id": uuid4(), "tid": other},
            )
        await conn.execute(text("ROLLBACK"))
