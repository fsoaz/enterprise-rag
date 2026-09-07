"""Dense retrieval via pgvector cosine (architecture § 7.4)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chunk, ChunkEmbedding, Document, DocumentVersion
from domain.embeddings import embedding_model_meta
from domain.types import DEFAULT_TOP_K_RETRIEVAL, INJECTION_RISK_BLOCK
from retrieval.acl import AclResolution, document_acl_predicate
from retrieval.temporal import version_predicate

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DenseHit:
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    body: str
    score: float  # cosine similarity (1 - distance)
    injection_risk: float = 0.0


async def dense_search(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_vector: list[float],
    acl: AclResolution,
    as_of: datetime | None = None,
    top_k: int = DEFAULT_TOP_K_RETRIEVAL,
    embedding_model_name: str | None = None,
    embedding_model_version: str | None = None,
) -> list[DenseHit]:
    model_name, model_version = embedding_model_meta()
    model_name = embedding_model_name or model_name
    model_version = embedding_model_version or model_version
    # Cosine distance operator <=> ; similarity = 1 - distance.
    distance = ChunkEmbedding.embedding.cosine_distance(query_vector)

    stmt = (
        select(
            Chunk.id,
            Document.id,
            Chunk.document_version_id,
            Chunk.body,
            distance.label("distance"),
            Chunk.injection_risk,
        )
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
        .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Chunk.tenant_id == tenant_id,
            ChunkEmbedding.tenant_id == tenant_id,
            ChunkEmbedding.model_name == model_name,
            ChunkEmbedding.model_version == model_version,
            version_predicate(as_of),
            Document.archived_at.is_(None),
            Document.erased_at.is_(None),
            Chunk.injection_risk < INJECTION_RISK_BLOCK,
            document_acl_predicate(acl),
        )
        .order_by(distance)
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        logger.warning(
            "dense_search: zero embedding rows for model_name=%s model_version=%s "
            "(backend/version mismatch or empty corpus)",
            model_name,
            model_version,
        )
    return [
        DenseHit(
            chunk_id=row[0],
            document_id=row[1],
            document_version_id=row[2],
            body=row[3],
            score=1.0 - float(row[4]),
            injection_risk=float(row[5] or 0.0),
        )
        for row in rows
    ]


async def embed_query(
    session: AsyncSession,
    query: str,
    *,
    embedding_model_name: str | None = None,
    embedding_model_version: str | None = None,
    inference_endpoint: str | None = None,
) -> list[float]:
    """Unused DB session kept for interface symmetry; embedding is via inference HTTP."""
    del session  # interface symmetry with other stages
    import httpx

    from domain.errors import InferenceUnavailable
    from retrieval.rerank import inference_base_url, inference_headers

    expected_name, expected_version = embedding_model_meta()
    expected_name = embedding_model_name or expected_name
    expected_version = embedding_model_version or expected_version

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{(inference_endpoint or inference_base_url()).rstrip('/')}/v1/embed",
                json={"texts": [query], "mode": "query"},
                headers=inference_headers(),
            )
            response.raise_for_status()
            payload = response.json()
            if (embedding_model_name is not None or embedding_model_version is not None) and (
                payload.get("model") != expected_name or payload.get("version") != expected_version
            ):
                raise InferenceUnavailable(
                    "query embed model identity mismatch: "
                    f"requested {expected_name}@{expected_version}, "
                    f"received {payload.get('model')}@{payload.get('version')}"
                )
            vectors = payload["vectors"]
            result: list[float] = list(vectors[0])
            return result
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        raise InferenceUnavailable(f"query embed failed: {exc}") from exc
