"""Real Postgres filtering with deterministic vectors; no semantic quality claim."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from evals.harness import corpus
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from tests.integration_database import integration_database_urls

from api.services.chat import run_chat
from db.models import AclEntry, Chunk, Document, DocumentVersion, Tenant, User
from db.session import set_tenant_context
from domain.types import EMBEDDING_DIM, RetrievalStrategy
from retrieval import pipeline
from retrieval.rerank import RerankResult

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("strategy", ["dense_only", "lexical_only", "hybrid_rrf", "hybrid_rerank"])
async def test_historical_access_uses_present_controls(
    monkeypatch: pytest.MonkeyPatch, strategy: str
) -> None:
    url, _ = integration_database_urls()
    engine = create_async_engine(url)
    vector = [1.0] + [0.0] * (EMBEDDING_DIM - 1)

    async def embeddings(texts: list[str]) -> list[list[float]]:
        return [vector for _ in texts]

    async def rerank(query: str, documents: list[str], *, top_k: int) -> list[RerankResult]:
        return [RerankResult(i, 1.0) for i in range(min(top_k, len(documents)))]

    monkeypatch.setenv("INFERENCE_BACKEND", "stub")
    monkeypatch.setattr(corpus, "embed_passages", embeddings)
    monkeypatch.setattr(pipeline, "embed_query", AsyncMock(return_value=vector))
    monkeypatch.setattr(pipeline, "rerank_documents", rerank)
    try:
        async with AsyncSession(engine) as session:
            tenant = await session.scalar(select(Tenant.id).where(Tenant.slug == "acme"))
            assert tenant is not None
            await set_tenant_context(session, tenant)
            user = await session.scalar(
                select(User.id).where(User.external_subject == "acme-member")
            )
            assert user is not None
            labels = await corpus.load_corpus(session, tenant_id=tenant)
            old, new = labels["chunk-hr-v1"], labels["chunk-hr-v2"]
            document_id = await session.scalar(
                select(DocumentVersion.document_id).where(DocumentVersion.id == old)
            )
            assert document_id is not None
            instant = datetime(2024, 8, 31, tzinfo=UTC)

            async def versions(as_of: datetime | None) -> set:
                result = await pipeline.retrieve(
                    session,
                    tenant_id=tenant,
                    user_id=user,
                    query="remote work policy",
                    strategy=strategy,
                    as_of=as_of,
                    top_k=50,
                )
                return {
                    h.document_version_id for h in [*result.hits, *result.lexical_evidence_hits]
                }

            assert old in await versions(instant)
            assert new not in await versions(instant)
            boundary = await versions(datetime(2024, 9, 1, tzinfo=UTC))
            assert new in boundary and old not in boundary
            assert old not in await versions(None)
            assert old not in await versions(datetime(2023, 1, 1, tzinfo=UTC))
            events = [
                event
                async for event in run_chat(
                    session,
                    tenant_id=tenant,
                    user_id=user,
                    question="remote work policy",
                    strategy=RetrievalStrategy(strategy),
                    as_of=instant,
                    anthropic_api_key="",
                )
            ]
            citations = [event["data"] for event in events if event["event"] == "citation"]
            assert citations
            assert {citation["document_version_id"] for citation in citations} == {str(old)}
            for field in ("archived_at", "erased_at"):
                await session.execute(
                    update(Document).where(Document.id == document_id).values({field: instant})
                )
                assert old not in await versions(instant)
                await session.execute(
                    update(Document).where(Document.id == document_id).values({field: None})
                )
            await session.execute(
                update(Chunk).where(Chunk.document_version_id == old).values(injection_risk=1.0)
            )
            assert old not in await versions(instant)
            await session.execute(
                update(Chunk).where(Chunk.document_version_id == old).values(injection_risk=0.0)
            )
            assert old in await versions(instant)
            # Revocation at the current time must hide even the older version.
            await session.execute(
                update(AclEntry).where(AclEntry.tenant_id == tenant).values(effect="deny")
            )
            assert old not in await versions(instant)
            await session.execute(
                update(AclEntry).where(AclEntry.tenant_id == tenant).values(effect="allow")
            )
            assert old in await versions(instant)
            globex = await session.scalar(select(Tenant.id).where(Tenant.slug == "globex"))
            assert globex is not None
            await set_tenant_context(session, globex)
            assert not await versions(instant)
            await session.rollback()
    finally:
        await engine.dispose()
