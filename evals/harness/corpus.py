"""Load the eval fixture corpus into the database.

The datasets reference gold passages by symbolic label (``chunk-security-en``).
This module materialises each label as a real document version — parsed, chunked,
embedded, and FTS-indexed through the same worker pipeline the product uses — and
returns the ``label -> document_version_id`` mapping the harness scores against.

Idempotent: re-running replaces the chunks for each version in place.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    AclEntry,
    Chunk,
    ChunkEmbedding,
    Collection,
    Document,
    DocumentVersion,
    Group,
    Tenant,
)
from domain.types import (
    AclEffect,
    AclPermission,
    AclResourceType,
    AclSubjectType,
    ParseStatus,
)
from worker.pipeline.chunk import chunk_document
from worker.pipeline.embed import embed_passages, embedding_model_meta
from worker.pipeline.index import index_chunks_search_vectors
from worker.pipeline.parse import parse_bytes

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "evals" / "corpus.json"
FIXTURE_DIR = REPO_ROOT / "evals" / "fixtures"


class CorpusError(RuntimeError):
    """Raised when the corpus cannot be loaded or resolved."""


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


async def resolve_tenant_id(session: AsyncSession, slug: str) -> UUID:
    tenant_id = await session.scalar(select(Tenant.id).where(Tenant.slug == slug))
    if tenant_id is None:
        raise CorpusError(f"tenant {slug!r} not found — run `make seed` first")
    return UUID(str(tenant_id))


async def _ensure_collection(
    session: AsyncSession, tenant_id: UUID, spec: dict[str, object]
) -> UUID:
    name = str(spec["name"])
    collection = await session.scalar(
        select(Collection).where(
            Collection.tenant_id == tenant_id,
            Collection.name == name,
        )
    )
    if collection is None:
        collection = Collection(
            id=uuid4(),
            tenant_id=tenant_id,
            name=name,
            description=str(spec.get("description") or ""),
        )
        session.add(collection)
        await session.flush()

    for group_name in [str(g) for g in spec.get("read_groups", [])]:  # type: ignore[union-attr]
        group_id = await session.scalar(
            select(Group.id).where(Group.tenant_id == tenant_id, Group.name == group_name)
        )
        if group_id is None:
            raise CorpusError(f"group {group_name!r} not found — run `make seed` first")
        existing = await session.scalar(
            select(AclEntry).where(
                AclEntry.tenant_id == tenant_id,
                AclEntry.subject_type == AclSubjectType.GROUP.value,
                AclEntry.subject_id == str(group_id),
                AclEntry.resource_type == AclResourceType.COLLECTION.value,
                AclEntry.resource_id == collection.id,
                AclEntry.permission == AclPermission.READ.value,
            )
        )
        if existing is None:
            session.add(
                AclEntry(
                    tenant_id=tenant_id,
                    subject_type=AclSubjectType.GROUP.value,
                    subject_id=str(group_id),
                    resource_type=AclResourceType.COLLECTION.value,
                    resource_id=collection.id,
                    permission=AclPermission.READ.value,
                    effect=AclEffect.ALLOW.value,
                )
            )
    await session.flush()
    return UUID(str(collection.id))


async def _ensure_version_chunks(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: DocumentVersion,
    fixture: Path,
) -> None:
    raw = fixture.read_bytes()
    parsed = parse_bytes(raw, mime_type="text/markdown", filename=fixture.name)
    text_chunks = chunk_document(parsed)
    if not text_chunks:
        raise CorpusError(f"fixture {fixture.name} produced no chunks")

    stale = (
        await session.scalars(select(Chunk).where(Chunk.document_version_id == version.id))
    ).all()
    for old in stale:
        await session.delete(old)
    await session.flush()

    rows: list[Chunk] = []
    for tc in text_chunks:
        row = Chunk(
            tenant_id=tenant_id,
            document_version_id=version.id,
            ordinal=tc.ordinal,
            body=tc.body,
            token_count=tc.token_count,
            page_from=tc.page_from,
            page_to=tc.page_to,
            section_path=tc.section_path,
            language=tc.language,
            injection_risk=tc.injection_risk,
        )
        session.add(row)
        rows.append(row)
    await session.flush()

    model_name, model_version = embedding_model_meta()
    vectors = await embed_passages([r.body for r in rows])
    for row, vector in zip(rows, vectors, strict=True):
        session.add(
            ChunkEmbedding(
                chunk_id=row.id,
                tenant_id=tenant_id,
                model_name=model_name,
                model_version=model_version,
                embedding=vector,
            )
        )
    await session.flush()
    await index_chunks_search_vectors(session, chunk_ids=[r.id for r in rows], tenant_id=tenant_id)
    version.parse_status = ParseStatus.SUCCEEDED.value
    version.page_count = len(parsed.pages) or None
    await session.flush()


async def resolve_existing_labels(
    session: AsyncSession,
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    tenant_id: UUID,
) -> dict[str, UUID]:
    """Map labels to already-loaded version IDs without touching the corpus."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    labels: dict[str, UUID] = {}
    for doc_spec in manifest["documents"]:
        document_id = await session.scalar(
            select(Document.id).where(
                Document.tenant_id == tenant_id,
                Document.title == str(doc_spec["title"]),
            )
        )
        if document_id is None:
            continue
        for version_no, ver_spec in enumerate(doc_spec["versions"], start=1):
            version_id = await session.scalar(
                select(DocumentVersion.id).where(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.version_no == version_no,
                )
            )
            if version_id is not None:
                labels[str(ver_spec["label"])] = UUID(str(version_id))
    return labels


async def load_corpus(
    session: AsyncSession,
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    tenant_id: UUID,
) -> dict[str, UUID]:
    """Materialise the manifest and return ``label -> document_version_id``."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    collection_ids: dict[str, UUID] = {}
    for spec in manifest["collections"]:
        collection_ids[str(spec["name"])] = await _ensure_collection(session, tenant_id, spec)

    labels: dict[str, UUID] = {}
    for doc_spec in manifest["documents"]:
        title = str(doc_spec["title"])
        collection_id = collection_ids[str(doc_spec["collection"])]
        document = await session.scalar(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.title == title,
            )
        )
        if document is None:
            document = Document(
                id=uuid4(),
                tenant_id=tenant_id,
                collection_id=collection_id,
                title=title,
                language=str(doc_spec.get("language", "en")),
            )
            session.add(document)
            await session.flush()

        for version_no, ver_spec in enumerate(doc_spec["versions"], start=1):
            label = str(ver_spec["label"])
            fixture = FIXTURE_DIR / str(ver_spec["fixture"])
            if not fixture.is_file():
                raise CorpusError(f"missing fixture {fixture}")

            version = await session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.version_no == version_no,
                )
            )
            if version is None:
                version = DocumentVersion(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    document_id=document.id,
                    version_no=version_no,
                    content_sha256=f"eval-{label}",
                    storage_key=f"evals/fixtures/{fixture.name}",
                    mime_type="text/markdown",
                    effective_from=_parse_ts(ver_spec.get("effective_from")) or datetime.now(UTC),
                    parse_status=ParseStatus.PENDING.value,
                )
                session.add(version)
                await session.flush()
            # `current` drives effective_to: retrieval only sees the open version.
            version.effective_to = (
                None if ver_spec.get("current") else _parse_ts(ver_spec.get("effective_to"))
            )
            await session.flush()

            await _ensure_version_chunks(
                session, tenant_id=tenant_id, version=version, fixture=fixture
            )
            labels[label] = UUID(str(version.id))

    return labels
