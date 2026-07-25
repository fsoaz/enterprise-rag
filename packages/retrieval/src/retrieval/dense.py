"""Dense retrieval via pgvector cosine (architecture § 7.4)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chunk, ChunkEmbedding, Document, DocumentVersion
from domain.types import DEFAULT_TOP_K_RETRIEVAL
from retrieval.acl import AclResolution, document_acl_predicate


@dataclass(frozen=True, slots=True)
class DenseHit:
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    body: str
    score: float  # cosine similarity (1 - distance)


def _active_embedding_meta() -> tuple[str, str]:
    return (
        os.environ.get("EMBEDDING_MODEL_NAME", "BAAI/bge-m3"),
        os.environ.get("EMBEDDING_MODEL_VERSION", "stub-v0"),
    )


async def dense_search(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_vector: list[float],
    acl: AclResolution,
    top_k: int = DEFAULT_TOP_K_RETRIEVAL,
) -> list[DenseHit]:
    model_name, model_version = _active_embedding_meta()
    # Cosine distance operator <=> ; similarity = 1 - distance.
    distance = ChunkEmbedding.embedding.cosine_distance(query_vector)

    stmt = (
        select(
            Chunk.id,
            Document.id,
            Chunk.document_version_id,
            Chunk.body,
            distance.label("distance"),
        )
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
        .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Chunk.tenant_id == tenant_id,
            ChunkEmbedding.tenant_id == tenant_id,
            ChunkEmbedding.model_name == model_name,
            ChunkEmbedding.model_version == model_version,
            DocumentVersion.effective_to.is_(None),
            Document.archived_at.is_(None),
            Document.erased_at.is_(None),
            document_acl_predicate(acl),
        )
        .order_by(distance)
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()
    return [
        DenseHit(
            chunk_id=row[0],
            document_id=row[1],
            document_version_id=row[2],
            body=row[3],
            score=1.0 - float(row[4]),
        )
        for row in rows
    ]


async def embed_query(session: AsyncSession, query: str) -> list[float]:
    """Unused DB session kept for interface symmetry; embedding is via inference HTTP."""
    del session  # interface symmetry with other stages
    import httpx

    from domain.errors import InferenceUnavailable

    base = os.environ.get("INFERENCE_BASE_URL", "http://localhost:8001").rstrip("/")
    headers: dict[str, str] = {}
    token = os.environ.get("INFERENCE_SERVICE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base}/v1/embed",
                json={"texts": [query], "mode": "query"},
                headers=headers,
            )
            response.raise_for_status()
            vectors = response.json()["vectors"]
            result: list[float] = list(vectors[0])
            return result
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        raise InferenceUnavailable(f"query embed failed: {exc}") from exc
