"""Source-label bindings resolve from Postgres under tenant RLS (ADR-016)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from tests.integration_database import integration_database_urls

from db.models import Collection, Document, DocumentVersion, Tenant
from db.session import set_tenant_context
from evaluation.labels import bind_label, resolve_labels

pytestmark = pytest.mark.integration


async def test_resolve_labels__bound_version__resolves_only_inside_its_tenant() -> None:
    url, _ = integration_database_urls()
    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as session:
            acme = await session.scalar(select(Tenant.id).where(Tenant.slug == "acme"))
            globex = await session.scalar(select(Tenant.id).where(Tenant.slug == "globex"))
            assert acme is not None and globex is not None
            await set_tenant_context(session, acme)

            suffix = uuid4().hex[:8]
            collection = Collection(tenant_id=acme, name=f"label-binding-{suffix}")
            session.add(collection)
            await session.flush()
            document = Document(tenant_id=acme, collection_id=collection.id, title="binding")
            session.add(document)
            await session.flush()
            versions = []
            for version_no in (1, 2):
                version = DocumentVersion(
                    tenant_id=acme,
                    document_id=document.id,
                    version_no=version_no,
                    content_sha256=f"{version_no}" * 64,
                    storage_key=f"test/{suffix}/{version_no}",
                    mime_type="text/markdown",
                    effective_from=datetime.now(UTC),
                    effective_to=datetime.now(UTC) if version_no == 1 else None,
                )
                session.add(version)
                await session.flush()
                versions.append(version.id)

            label = f"test-label-{suffix}"
            await bind_label(session, tenant_id=acme, label=label, document_version_id=versions[0])
            # Reloading the corpus rebinds rather than failing on the existing label.
            await bind_label(session, tenant_id=acme, label=label, document_version_id=versions[1])

            assert await resolve_labels(session, tenant_id=acme, labels=[label, "unbound"]) == {
                label: versions[1]
            }
            assert label in await resolve_labels(session, tenant_id=acme)
            assert await resolve_labels(session, tenant_id=acme, labels=[]) == {}

            # RLS, not the explicit filter: acme's binding is invisible under globex's
            # tenant context even when the query names acme.
            await set_tenant_context(session, globex)
            assert await resolve_labels(session, tenant_id=acme, labels=[label]) == {}
            assert await resolve_labels(session, tenant_id=globex, labels=[label]) == {}
            await session.rollback()
    finally:
        await engine.dispose()
