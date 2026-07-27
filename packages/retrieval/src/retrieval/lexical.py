"""Lexical FTS retrieval (architecture § 7.5)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from db.models import Chunk, Document, DocumentVersion
from domain.types import DEFAULT_TOP_K_RETRIEVAL, INJECTION_RISK_BLOCK
from retrieval.acl import AclResolution, document_acl_predicate

LEXICAL_MIN_RANK = 0.01
# A chunk only counts as degraded-mode evidence when at least this many *distinct*
# content lexemes of the question appear in it. One shared common word ("next")
# scores far above any workable rank floor while saying nothing about relevance,
# so the signal has to be term count, not rank.
LEXICAL_MIN_EVIDENCE_TERMS = 2
_QUERY_TERM = re.compile(r"[^\W_]+", re.UNICODE)


def _or_tsquery(query: str) -> str:
    """Turn question terms into an OR query without accepting tsquery syntax."""
    terms = _QUERY_TERM.findall(query)
    return " OR ".join(terms)


def _content_lexemes(config: str, query: str) -> ColumnElement[list[str]]:
    """The question's content lexemes under ``config``, with its stop words removed.

    Stop words are a property of the dictionary, not of the string, so this has to
    be resolved by the same config that will parse the corpus side. Parsing an
    English question with the Portuguese dictionary leaves ``is``/``the``/``of``
    standing as ordinary lexemes, and those match nearly every English chunk —
    which is how a question with no content words at all certified itself as
    grounded. Returns an empty array for such a question.
    """
    return func.tsvector_to_array(func.strip(func.to_tsvector(config, query)))


def _matched_term_count(config: str, query: str) -> ColumnElement[int]:
    """How many distinct content lexemes of the question this chunk contains."""
    lexeme = func.unnest(_content_lexemes(config, query)).column_valued("lexeme")
    return (
        select(func.count())
        .where(lexeme == func.any(func.tsvector_to_array(Chunk.search_vector)))
        .scalar_subquery()
    )


@dataclass(frozen=True, slots=True)
class LexicalHit:
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    body: str
    score: float
    primary_score: float
    matched_terms: int = 0
    injection_risk: float = 0.0

    @property
    def is_evidence(self) -> bool:
        """Strong enough to show as a source when generation is unavailable."""
        return self.matched_terms >= LEXICAL_MIN_EVIDENCE_TERMS


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
    # plainto_tsquery combines every question term with AND, so a natural query
    # such as "password rotation period" misses a passage containing only
    # "password" and "rotated". OR semantics retrieves partial lexical evidence;
    # the rank floor below keeps incidental one-token matches out.
    query_terms = _or_tsquery(query)
    tsq_primary = func.websearch_to_tsquery(config, query_terms)
    tsq_secondary = func.websearch_to_tsquery(
        "english" if config == "portuguese" else "portuguese", query_terms
    )
    primary_rank = func.ts_rank_cd(Chunk.search_vector, tsq_primary)
    rank = func.greatest(primary_rank, func.ts_rank_cd(Chunk.search_vector, tsq_secondary))

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
            primary_rank.label("primary_rank"),
            _matched_term_count(config, query).label("matched_terms"),
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
            rank >= LEXICAL_MIN_RANK,
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
            primary_score=float(row[5] or 0.0),
            matched_terms=int(row[6] or 0),
            injection_risk=float(row[7] or 0.0),
        )
        for row in rows
    ]
