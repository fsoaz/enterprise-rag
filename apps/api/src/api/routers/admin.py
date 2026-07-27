"""Administrative operations: irreversible document erasure.

``DELETE /documents/{id}`` has always returned 405 pointing callers here, and
retrieval has always filtered on ``erased_at`` — but nothing ever set it, no route
existed, and ``erasure_log`` was never written. Right-to-erasure was documented,
filtered for, and impossible to actually perform.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.auth import AclAdminUser
from api.deps.db import get_db_session
from api.pagination import apply_descending_cursor, page_limit, page_rows
from api.services import storage
from db.models import Chunk, Document, DocumentVersion, ErasureLog, QueryCitation
from domain.errors import ConflictError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


class EraseRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    legal_basis: str = Field(min_length=1, max_length=200)


class EraseResponse(BaseModel):
    document_id: UUID
    erased_at: datetime
    versions_affected: int
    citations_affected: int
    objects_deleted: int


class ErasureOut(BaseModel):
    id: UUID
    document_id: UUID
    actor_user_id: UUID | None
    reason: str
    legal_basis: str
    versions_affected: int
    citations_affected: int
    created_at: datetime


class ErasurePage(BaseModel):
    data: list[ErasureOut]
    next_cursor: str | None


@router.get("/erasures", response_model=ErasurePage)
async def list_erasures(
    user: AclAdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = 200,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> ErasurePage:
    limit = page_limit(limit)
    stmt = apply_descending_cursor(
        select(ErasureLog).where(ErasureLog.tenant_id == user.tenant_id),
        created_column=ErasureLog.created_at,
        id_column=ErasureLog.id,
        cursor=cursor,
    )
    fetched = (
        await session.scalars(
            stmt.order_by(ErasureLog.created_at.desc(), ErasureLog.id.desc()).limit(limit + 1)
        )
    ).all()
    rows, next_cursor = page_rows(
        fetched,
        limit=limit,
        created_at=lambda row: row.created_at,
        item_id=lambda row: row.id,
    )
    return ErasurePage(
        data=[
            ErasureOut(
                id=row.id,
                document_id=row.document_id,
                actor_user_id=row.actor_user_id,
                reason=row.reason,
                legal_basis=row.legal_basis,
                versions_affected=row.versions_affected,
                citations_affected=row.citations_affected,
                created_at=row.created_at,
            )
            for row in rows
        ],
        next_cursor=next_cursor,
    )


@router.post("/documents/{document_id}/erase", response_model=EraseResponse)
async def erase_document(
    document_id: UUID,
    body: EraseRequest,
    user: AclAdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EraseResponse:
    """Destroy document content irreversibly, keeping an audit record.

    Chunks and embeddings are deleted outright, which cascades to the citations
    that pointed at them — erased text must not survive in a stored answer. The
    ``documents`` and ``document_versions`` rows are retained (with ``erased_at``
    set) so existing references resolve to a tombstone rather than a dangling id,
    and so the erasure itself stays auditable.
    """
    doc = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == user.tenant_id,
        )
    )
    if doc is None:
        raise NotFoundError(f"No document {document_id}")
    if doc.erased_at is not None:
        raise ConflictError(f"Document {document_id} is already erased")
    if doc.legal_hold:
        raise ConflictError(
            f"Document {document_id} is under legal hold and cannot be erased. "
            "Clear the hold first."
        )

    versions = (
        await session.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == document_id)
        )
    ).all()
    version_ids = [v.id for v in versions]

    citations_affected = 0
    if version_ids:
        citations_affected = int(
            await session.scalar(
                select(func.count())
                .select_from(QueryCitation)
                .where(QueryCitation.document_version_id.in_(version_ids))
            )
            or 0
        )
        # Cascades to chunk_embeddings and query_citations via their foreign keys.
        await session.execute(delete(Chunk).where(Chunk.document_version_id.in_(version_ids)))

    erased_at = datetime.now(UTC)
    doc.erased_at = erased_at
    doc.archived_at = doc.archived_at or erased_at

    session.add(
        ErasureLog(
            tenant_id=user.tenant_id,
            document_id=document_id,
            actor_user_id=user.user_id,
            reason=body.reason,
            legal_basis=body.legal_basis,
            versions_affected=len(version_ids),
            citations_affected=citations_affected,
        )
    )
    await session.flush()

    # Object removal last: the database record is the source of truth, and a
    # storage failure must not roll back an erasure the audit log already claims.
    def _delete(key: str) -> None:
        storage.delete_object(key=key)

    objects_deleted = 0
    for version in versions:
        try:
            await anyio.to_thread.run_sync(_delete, version.storage_key)
            objects_deleted += 1
        except Exception:
            logger.exception(
                "erasure: failed to delete object %s for document %s",
                version.storage_key,
                document_id,
            )

    return EraseResponse(
        document_id=document_id,
        erased_at=erased_at,
        versions_affected=len(version_ids),
        citations_affected=citations_affected,
        objects_deleted=objects_deleted,
    )
