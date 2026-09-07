from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    Table,
    create_engine,
    literal_column,
    select,
)

from retrieval import pipeline
from retrieval.temporal import version_predicate


@pytest.mark.parametrize(
    ("day", "expected"), [(None, [2]), (1, []), (2, [1]), (3, [1]), (4, [2]), (5, [2])]
)
def test_half_open_version_interval(day: int | None, expected: list[int]) -> None:
    # Execute the shared SQL predicate with exact interval boundaries.
    table = Table(
        "document_versions",
        MetaData(),
        Column("id", Integer),
        Column("effective_from", DateTime(timezone=True)),
        Column("effective_to", DateTime(timezone=True)),
    )
    engine = create_engine("sqlite://")
    table.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            table.insert(),
            [
                {
                    "id": 1,
                    "effective_from": datetime(2026, 1, 2),
                    "effective_to": datetime(2026, 1, 4),
                },
                {"id": 2, "effective_from": datetime(2026, 1, 4), "effective_to": None},
            ],
        )
        instant = datetime(2026, 1, day, tzinfo=UTC) if day else None
        assert (
            list(
                connection.scalars(
                    select(literal_column("document_versions.id")).where(version_predicate(instant))
                )
            )
            == expected
        )
    engine.dispose()


@pytest.mark.parametrize("strategy", ["dense_only", "lexical_only", "hybrid_rrf", "hybrid_rerank"])
async def test_all_strategies_filter_lexical_evidence(
    monkeypatch: pytest.MonkeyPatch, strategy: str
) -> None:
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    acl = AsyncMock()
    dense = AsyncMock(return_value=[])
    lexical = AsyncMock(return_value=[])
    monkeypatch.setattr(pipeline, "resolve_acl", AsyncMock(return_value=acl))
    monkeypatch.setattr(pipeline, "embed_query", AsyncMock(return_value=[0.0]))
    monkeypatch.setattr(pipeline, "dense_search", dense)
    monkeypatch.setattr(pipeline, "lexical_search", lexical)
    await pipeline.retrieve(
        AsyncMock(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        query="policy",
        as_of=instant,
        strategy=strategy,
    )
    lexical.assert_awaited_once()
    assert lexical.call_args.kwargs["as_of"] == instant
    if strategy != "lexical_only":
        dense.assert_awaited_once()
        assert dense.call_args.kwargs["as_of"] == instant


async def test_direct_retrieval_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone"):
        await pipeline.retrieve(
            AsyncMock(),
            tenant_id=uuid4(),
            user_id=uuid4(),
            query="policy",
            as_of=datetime(2026, 1, 1),
        )


@pytest.mark.parametrize("arm", ["dense", "lexical"])
async def test_historical_query_retains_present_security_filters(arm: str) -> None:
    from unittest.mock import Mock

    from retrieval.acl import AclResolution, AclSubjectSet
    from retrieval.dense import dense_search
    from retrieval.lexical import lexical_search

    tenant, collection, denied = uuid4(), uuid4(), uuid4()
    acl = AclResolution(
        acl_version=3,
        subjects=AclSubjectSet(uuid4(), frozenset(), frozenset({"viewer"}), False),
        allowed_collection_ids=frozenset({collection}),
        allowed_document_ids=frozenset(),
        denied_document_ids=frozenset({denied}),
    )
    session = AsyncMock()
    session.execute.return_value = Mock(all=Mock(return_value=[]))
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    if arm == "dense":
        await dense_search(session, tenant_id=tenant, query_vector=[0.0], acl=acl, as_of=instant)
    else:
        await lexical_search(session, tenant_id=tenant, query="policy", acl=acl, as_of=instant)
    statement = session.execute.call_args.args[0]
    sql = str(statement)
    assert "chunks.tenant_id =" in sql
    assert "documents.archived_at IS NULL" in sql
    assert "documents.erased_at IS NULL" in sql
    assert "chunks.injection_risk <" in sql
    assert "document_versions.effective_from <=" in sql
    assert "document_versions.effective_to >" in sql
    assert "documents.id NOT IN" in sql
    assert "documents.collection_id IN" in sql
    parameters = statement.compile().params
    assert tenant in parameters.values()
    assert [denied] in parameters.values()
    assert [collection] in parameters.values()
