"""Write dual-language FTS search_vector on chunks (architecture § 7.5)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

# portuguese weight A + english weight B — both configs always indexed.
_SEARCH_VECTOR_SQL = text(
    """
    UPDATE chunks
       SET search_vector =
             setweight(to_tsvector('portuguese', body), 'A')
             || setweight(to_tsvector('english', body), 'B'),
           updated_at = now()
     WHERE id IN :chunk_ids
       AND tenant_id = :tenant_id
    """
).bindparams(bindparam("chunk_ids", expanding=True))

# Bound so a large document does not build one enormous statement.
_INDEX_BATCH_SIZE = 500


async def index_chunks_search_vectors(
    session: AsyncSession,
    *,
    chunk_ids: list[UUID],
    tenant_id: UUID,
) -> None:
    """Populate search_vector for the given chunks in batched UPDATEs."""
    for start in range(0, len(chunk_ids), _INDEX_BATCH_SIZE):
        batch = chunk_ids[start : start + _INDEX_BATCH_SIZE]
        if not batch:
            continue
        await session.execute(
            _SEARCH_VECTOR_SQL,
            {"chunk_ids": batch, "tenant_id": tenant_id},
        )


async def index_chunk_search_vector(
    session: AsyncSession,
    *,
    chunk_id: UUID,
    tenant_id: UUID,
) -> None:
    await index_chunks_search_vectors(session, chunk_ids=[chunk_id], tenant_id=tenant_id)
