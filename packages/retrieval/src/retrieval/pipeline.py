"""Retrieval orchestration — configurable strategies (architecture § 7.9)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from domain.text import detect_supported_language
from domain.types import (
    DEFAULT_RRF_K,
    DEFAULT_TOP_K_RERANK,
    DEFAULT_TOP_K_RETRIEVAL,
    INJECTION_RISK_FLAG,
    RetrievalStrategy,
)
from retrieval.acl import resolve_acl
from retrieval.dense import dense_search, embed_query
from retrieval.fusion import reciprocal_rank_fusion
from retrieval.lexical import LEXICAL_MIN_EVIDENCE_TERMS, lexical_search
from retrieval.rerank import rerank_documents


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    body: str
    score: float
    matched_lexical_terms: int = 0
    injection_risk: float = 0.0

    @property
    def is_suspect(self) -> bool:
        """Chunk carries instruction-like content and should be labelled untrusted."""
        return self.injection_risk >= INJECTION_RISK_FLAG


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    hits: list[RetrievalHit]
    strategy: str
    acl_version: int
    has_lexical_match: bool
    lexical_evidence_hits: list[RetrievalHit]


def _detect_language_hint(query: str) -> str:
    return detect_supported_language(query)


async def retrieve(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    query: str,
    strategy: RetrievalStrategy | str = RetrievalStrategy.HYBRID_RRF,
    top_k: int = DEFAULT_TOP_K_RERANK,
    retrieval_k: int = DEFAULT_TOP_K_RETRIEVAL,
    rrf_k: int = DEFAULT_RRF_K,
) -> RetrievalResult:
    strategy_value = strategy.value if isinstance(strategy, RetrievalStrategy) else str(strategy)
    acl = await resolve_acl(session, tenant_id=tenant_id, user_id=user_id)
    lang = _detect_language_hint(query)

    dense_hits: list[RetrievalHit] = []
    lexical_hits: list[RetrievalHit] = []

    need_dense = strategy_value in {
        RetrievalStrategy.DENSE_ONLY.value,
        RetrievalStrategy.HYBRID_RRF.value,
        RetrievalStrategy.HYBRID_RERANK.value,
    }
    need_lexical = strategy_value in {
        RetrievalStrategy.LEXICAL_ONLY.value,
        RetrievalStrategy.HYBRID_RRF.value,
        RetrievalStrategy.HYBRID_RERANK.value,
    }

    if need_dense:
        vector = await embed_query(session, query)
        for dhit in await dense_search(
            session,
            tenant_id=tenant_id,
            query_vector=vector,
            acl=acl,
            top_k=retrieval_k,
        ):
            dense_hits.append(
                RetrievalHit(
                    chunk_id=dhit.chunk_id,
                    document_id=dhit.document_id,
                    document_version_id=dhit.document_version_id,
                    body=dhit.body,
                    score=dhit.score,
                    injection_risk=dhit.injection_risk,
                )
            )

    # Even dense_only needs lexical evidence in degraded mode: hash vectors make
    # a rank available for every query, which is not relevance evidence. This
    # does not alter dense-only ranking; it only provides safe fallback sources.
    if need_lexical or strategy_value == RetrievalStrategy.DENSE_ONLY.value:
        for lhit in await lexical_search(
            session,
            tenant_id=tenant_id,
            query=query,
            acl=acl,
            top_k=retrieval_k,
            language_hint=lang,
        ):
            lexical_hits.append(
                RetrievalHit(
                    chunk_id=lhit.chunk_id,
                    document_id=lhit.document_id,
                    document_version_id=lhit.document_version_id,
                    body=lhit.body,
                    score=lhit.score,
                    matched_lexical_terms=lhit.matched_terms,
                    injection_risk=lhit.injection_risk,
                )
            )

    if strategy_value == RetrievalStrategy.DENSE_ONLY.value:
        hits = dense_hits[:top_k]
    elif strategy_value == RetrievalStrategy.LEXICAL_ONLY.value:
        hits = lexical_hits[:top_k]
    else:
        # hybrid_rrf / hybrid_rerank
        by_id: dict[UUID, RetrievalHit] = {h.chunk_id: h for h in (*dense_hits, *lexical_hits)}
        fused = reciprocal_rank_fusion(
            [
                [h.chunk_id for h in dense_hits],
                [h.chunk_id for h in lexical_hits],
            ],
            k=rrf_k,
        )
        fused_hits = [
            RetrievalHit(
                chunk_id=cid,
                document_id=by_id[cid].document_id,
                document_version_id=by_id[cid].document_version_id,
                body=by_id[cid].body,
                score=score,
                injection_risk=by_id[cid].injection_risk,
            )
            for cid, score in fused
            if cid in by_id
        ]

        if strategy_value == RetrievalStrategy.HYBRID_RERANK.value and fused_hits:
            # Rerank up to retrieval_k candidates, keep top_k.
            candidates = fused_hits[:retrieval_k]
            reranked = await rerank_documents(
                query,
                [h.body for h in candidates],
                top_k=min(top_k, len(candidates)),
            )
            hits = [
                RetrievalHit(
                    chunk_id=candidates[r.index].chunk_id,
                    document_id=candidates[r.index].document_id,
                    document_version_id=candidates[r.index].document_version_id,
                    body=candidates[r.index].body,
                    score=r.score,
                    injection_risk=candidates[r.index].injection_risk,
                )
                for r in reranked
                if 0 <= r.index < len(candidates)
            ]
        else:
            hits = fused_hits[:top_k]

    return RetrievalResult(
        hits=hits,
        strategy=strategy_value,
        acl_version=acl.acl_version,
        has_lexical_match=bool(lexical_hits),
        # Evidence is the subset carrying enough distinct question terms to be
        # worth showing without a model to synthesise from. ``has_lexical_match``
        # above stays broad: it describes retrieval, not evidence.
        lexical_evidence_hits=[
            hit for hit in lexical_hits if hit.matched_lexical_terms >= LEXICAL_MIN_EVIDENCE_TERMS
        ][:top_k],
    )
