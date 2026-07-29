from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.sql.dml import Delete, Update

from api.routers.admin import EraseRequest, erase_document, redact_queries_for_erased_versions


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def all(self) -> list[object]:
        if isinstance(self._value, list):
            return list(self._value)
        return [self._value]


class _RecordingSession:
    """Minimal async session stand-in that records statement order."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._scalar_queue: list[object] = []
        self._scalars_queue: list[object] = []
        self.added: list[object] = []
        self.last_update: Update | None = None

    def queue_scalar(self, value: object) -> None:
        self._scalar_queue.append(value)

    def queue_scalars(self, value: object) -> None:
        self._scalars_queue.append(value)

    async def scalar(self, _stmt: object) -> object:
        self.calls.append("scalar")
        return self._scalar_queue.pop(0)

    async def scalars(self, _stmt: object) -> _ScalarResult:
        self.calls.append("scalars")
        return _ScalarResult(self._scalars_queue.pop(0))

    async def execute(self, stmt: object) -> None:
        if isinstance(stmt, Update):
            self.calls.append("update_query")
            self.last_update = stmt
        elif isinstance(stmt, Delete):
            self.calls.append("delete_chunk")
        else:
            self.calls.append(f"execute:{type(stmt).__name__}")

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.calls.append("flush")


@pytest.mark.asyncio
async def test_redact_queries_nulls_answer_for_cited_query() -> None:
    tenant_id = uuid4()
    version_id = uuid4()
    query_id = uuid4()
    chunk_id = uuid4()
    session = _RecordingSession()
    session.queue_scalar(1)  # citations count
    session.queue_scalars([chunk_id])  # chunk ids
    session.queue_scalars([query_id])  # cited query ids
    session.queue_scalars([])  # overlap query ids

    citations_affected, queries_affected = await redact_queries_for_erased_versions(
        session,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        version_ids=[version_id],
    )

    assert citations_affected == 1
    assert queries_affected == 1
    assert session.last_update is not None
    values = {col.key: elem.value for col, elem in session.last_update._values.items()}
    assert values["answer_text"] is None
    assert values["retrieved_chunk_ids"] is None


@pytest.mark.asyncio
async def test_erase_redacts_before_deleting_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ordering pin: citation cascade makes post-delete redaction a silent no-op."""
    order: list[str] = []
    doc_id = uuid4()
    tenant_id = uuid4()
    version_id = uuid4()

    doc = type(
        "Doc",
        (),
        {
            "id": doc_id,
            "tenant_id": tenant_id,
            "erased_at": None,
            "archived_at": None,
            "legal_hold": False,
        },
    )()
    version = type(
        "V",
        (),
        {"id": version_id, "storage_key": "tenant/doc/v1.bin", "document_id": doc_id},
    )()

    session = _RecordingSession()
    session.queue_scalar(doc)
    session.queue_scalars([version])

    async def fake_redact(
        _session: object, *, tenant_id: object, version_ids: list[object]
    ) -> tuple[int, int]:
        del tenant_id, version_ids
        order.append("redact")
        return 2, 1

    async def tracking_execute(stmt: object) -> None:
        if isinstance(stmt, Delete):
            order.append("delete_chunk")
        await _RecordingSession.execute(session, stmt)

    session.execute = tracking_execute  # type: ignore[method-assign]

    async def fake_run_sync(fn: object, key: str) -> None:
        del fn, key
        order.append("storage_delete")

    monkeypatch.setattr("api.routers.admin.redact_queries_for_erased_versions", fake_redact)
    monkeypatch.setattr("api.routers.admin.anyio.to_thread.run_sync", fake_run_sync)

    user = type("U", (), {"tenant_id": tenant_id, "user_id": uuid4()})()
    body = EraseRequest(reason="right to erasure", legal_basis="GDPR Art. 17")
    result = await erase_document(doc_id, body, user, session)  # type: ignore[arg-type]

    assert result.queries_affected == 1
    assert result.citations_affected == 2
    assert order.index("redact") < order.index("delete_chunk")
