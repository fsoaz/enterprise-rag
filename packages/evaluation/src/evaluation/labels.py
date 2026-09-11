"""Resolve symbolic evaluation source labels to document versions.

Datasets name gold and prohibited sources by label (``acme-aster-policy-v1``) so a
committed dataset never carries database identifiers. The offline corpus loader binds
each label to the document version it materialised; runtime resolution reads only those
bindings and never the fixture files, which no deployable image contains.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import EvalSourceLabel


async def resolve_labels(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    labels: Iterable[str] | None = None,
) -> dict[str, UUID]:
    """Map bound labels to version IDs. Unbound labels are absent from the result.

    ``labels=None`` returns every binding for the tenant.
    """
    stmt = select(EvalSourceLabel.label, EvalSourceLabel.document_version_id).where(
        EvalSourceLabel.tenant_id == tenant_id
    )
    if labels is not None:
        wanted = sorted(set(labels))
        if not wanted:
            return {}
        stmt = stmt.where(EvalSourceLabel.label.in_(wanted))
    rows = await session.execute(stmt)
    return {str(label): UUID(str(version_id)) for label, version_id in rows.all()}


async def bind_label(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    label: str,
    document_version_id: UUID,
) -> None:
    """Create or move one label binding. Idempotent, so corpus reloads are safe."""
    stmt = insert(EvalSourceLabel).values(
        tenant_id=tenant_id,
        label=label,
        document_version_id=document_version_id,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[EvalSourceLabel.tenant_id, EvalSourceLabel.label],
            set_={
                "document_version_id": stmt.excluded.document_version_id,
                "updated_at": func.now(),
            },
        )
    )
