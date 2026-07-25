"""Lexical FTS retrieval (architecture § 7.5)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from db.models import Chunk, Document, DocumentVersion
from domain.types import DEFAULT_TOP_K_RETRIEVAL, INJECTION_RISK_BLOCK
from retrieval.acl import AclResolution, document_acl_predicate


@dataclass(frozen=True, slots=True)
class LexicalHit:
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    body: str
    score: float
    injection_risk: float = 0.0


async def lexical_search(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query: str,
    acl: AclResolution,
    top_k: int = DEFAULT_TOP_K_RETRIEVAL,
    language_hint: str = "en",
) -> list[LexicalHit]:
    """FTS top-k under ACL + tenant + current version.

    Dual-language search_vector is always queried; language_hint selects which
    plainto_tsquery config is primary (both still match via the combined vector).
    """
    config = "portuguese" if language_hint == "pt" else "english"
    # Query both configs and take the better rank so PT↔EN cross-language works.
    tsq_primary = func.plainto_tsquery(config, query)
    tsq_secondary = func.plainto_tsquery(
        "english" if config == "portuguese" else "portuguese", query
    )
    rank = func.greatest(
        func.ts_rank_cd(Chunk.search_vector, tsq_primary),
        func.ts_rank_cd(Chunk.search_vector, tsq_secondary),
    )

    match_pred: ColumnElement[bool] = or_(
        Chunk.search_vector.op("@@")(tsq_primary),
        Chunk.search_vector.op("@@")(tsq_secondary),
    )

    stmt = (
        select(
            Chunk.id,
            Document.id,
            Chunk.document_version_id,
            Chunk.body,
            rank.label("rank"),
            Chunk.injection_risk,
        )
        .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Chunk.tenant_id == tenant_id,
            DocumentVersion.effective_to.is_(None),
            Document.archived_at.is_(None),
            Document.erased_at.is_(None),
            Chunk.search_vector.is_not(None),
            Chunk.injection_risk < INJECTION_RISK_BLOCK,
            match_pred,
            document_acl_predicate(acl),
        )
        .order_by(rank.desc())
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()
    return [
        LexicalHit(
            chunk_id=row[0],
            document_id=row[1],
            document_version_id=row[2],
            body=row[3],
            score=float(row[4] or 0.0),
            injection_risk=float(row[5] or 0.0),
        )
        for row in rows
    ]
