"""Documents API — upload, list, archive (no hard delete)."""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.auth import AuthUser, CuratorUser, CurrentUser
from api.deps.db import get_db_session
from api.deps.limits import UploadRateLimited
from api.pagination import apply_descending_cursor, page_limit, page_rows
from api.services import storage
from api.services.ingest import enqueue_ingest
from db.models import Collection, Document, DocumentVersion, IngestionJob
from domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from domain.text import looks_like_pdf, looks_like_text
from domain.types import AclPermission, IngestionStage, JobStatus, ParseStatus
from retrieval.acl import document_acl_predicate, resolve_acl

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

# Ingest supports PDF / Markdown / plain text. Anything else is rejected at the
# edge rather than failing deep inside the worker's parse stage.
ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "text/markdown",
        "text/x-markdown",
        "text/plain",
    }
)
_DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class UploadTooLargeError(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(
            f"Uploaded file exceeds the {limit} byte limit",
            type_slug="upload-too-large",
        )


class UnsupportedMediaTypeError(DomainError):
    def __init__(self, mime: str) -> None:
        super().__init__(
            f"Unsupported media type {mime!r}; expected PDF, Markdown, or plain text",
            type_slug="unsupported-media-type",
        )


def max_upload_bytes() -> int:
    raw = os.environ.get("MAX_UPLOAD_BYTES", "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        return _DEFAULT_MAX_UPLOAD_BYTES
    return int(raw)


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    """Stream the upload, aborting as soon as it exceeds ``limit``.

    Reading via ``await file.read()`` would buffer an arbitrarily large body into
    memory before any size check could run.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise UploadTooLargeError(limit)
        chunks.append(chunk)
    return b"".join(chunks)


async def _readable_documents(
    session: AsyncSession, user: AuthUser, *, stmt: Select[tuple[Document]]
) -> Select[tuple[Document]]:
    """Narrow a Document query to what the caller may actually read.

    RLS already scopes rows to the tenant; this adds the per-collection and
    per-document ACL that /search applies, so document metadata (titles,
    collection membership) is not enumerable by every tenant member.
    Erased documents are excluded here so every route that uses this helper
    returns 404 consistently.
    """
    resolution = await resolve_acl(
        session,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        permission=AclPermission.READ,
    )
    return stmt.where(Document.erased_at.is_(None), document_acl_predicate(resolution))


class DocumentOut(BaseModel):
    id: UUID
    collection_id: UUID
    title: str
    language: str
    archived_at: datetime | None
    created_at: datetime
    current_version_id: UUID | None = None


class JobOut(BaseModel):
    id: UUID
    document_version_id: UUID
    stage: str
    status: str
    attempts: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class DocumentPage(BaseModel):
    data: list[DocumentOut]
    next_cursor: str | None


class JobPage(BaseModel):
    data: list[JobOut]
    next_cursor: str | None


class UploadAccepted(BaseModel):
    document_id: UUID
    version_id: UUID
    job_id: UUID
    dispatch: str


class VersionOut(BaseModel):
    id: UUID
    version_no: int
    content_sha256: str
    effective_from: datetime
    effective_to: datetime | None
    parse_status: str


class VersionPage(BaseModel):
    data: list[VersionOut]
    next_cursor: str | None


def _detect_media_type(data: bytes, filename: str) -> str | None:
    """Resolve the media type from file *content*; ``None`` when unsupported.

    The declared ``Content-Type`` is attacker-controlled and is deliberately not
    trusted: the previous version accepted whatever the client claimed whenever it
    was not ``application/octet-stream``, so labelling an arbitrary binary
    ``text/plain`` walked straight past the allowlist. The extension only chooses
    between Markdown and plain text — both parse identically, so getting it wrong
    is cosmetic.
    """
    if looks_like_pdf(data):
        return "application/pdf"
    if looks_like_text(data):
        lower = filename.lower()
        if lower.endswith((".md", ".markdown")):
            return "text/markdown"
        return "text/plain"
    return None


async def _require_collection_write(
    session: AsyncSession, user: AuthUser, collection_id: UUID
) -> None:
    """Reject callers without WRITE on this specific collection.

    Holding a curator role is not enough. Every mutation of a document has to pass
    this, not just upload: archive and unarchive previously checked role + READ
    only, so a steward granted read-only access to a collection could pull any
    document in it out of retrieval for every user — a write-level effect reachable
    with read-level permission.
    """
    write_acl = await resolve_acl(
        session,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        permission=AclPermission.WRITE,
    )
    if not write_acl.subjects.is_admin and collection_id not in write_acl.allowed_collection_ids:
        raise PermissionDeniedError(f"No write permission on collection {collection_id}")


@router.post("", status_code=202, response_model=UploadAccepted)
async def upload_document(
    user: CuratorUser,
    _limited: UploadRateLimited,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    file: Annotated[UploadFile, File()],
    collection_id: Annotated[UUID, Form()],
    title: Annotated[str | None, Form(max_length=300)] = None,
    language: Annotated[str, Form(pattern="^(en|pt)$")] = "en",
    document_id: Annotated[UUID | None, Form()] = None,
) -> UploadAccepted:
    collection = await session.scalar(
        select(Collection).where(
            Collection.id == collection_id,
            Collection.tenant_id == user.tenant_id,
        )
    )
    if collection is None:
        raise NotFoundError(f"No collection {collection_id}")

    await _require_collection_write(session, user, collection_id)

    raw = await _read_capped(file, max_upload_bytes())
    if not raw:
        raise ValidationError("Uploaded file has no content")

    digest = hashlib.sha256(raw).hexdigest()
    filename = file.filename or "upload.bin"
    detected = _detect_media_type(raw, filename)
    if detected is None or detected not in ALLOWED_MIME_TYPES:
        raise UnsupportedMediaTypeError(file.content_type or "unknown")
    mime = detected
    doc_title = title or filename

    existing_version = await session.scalar(
        select(DocumentVersion)
        .join(Document)
        .where(
            Document.tenant_id == user.tenant_id,
            Document.collection_id == collection_id,
            Document.erased_at.is_(None),
            DocumentVersion.effective_to.is_(None),
            DocumentVersion.content_sha256 == digest,
        )
    )
    if existing_version is not None:
        raise ConflictError("An identical document version already exists in this collection")

    existing_document: Document | None = None
    if document_id is not None:
        existing_document = await session.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == user.tenant_id,
                Document.erased_at.is_(None),
            )
        )
        if existing_document is None:
            raise NotFoundError(f"No document {document_id}")
        if existing_document.collection_id != collection_id:
            raise ValidationError("A new version must remain in the document collection")
        await _require_collection_write(session, user, existing_document.collection_id)

    resolved_document_id = document_id or uuid4()
    version_id = uuid4()
    key = storage.storage_key(
        tenant_id=user.tenant_id,
        document_id=resolved_document_id,
        version_id=version_id,
        filename=filename,
    )

    if existing_document is None:
        document = Document(
            id=resolved_document_id,
            tenant_id=user.tenant_id,
            collection_id=collection_id,
            title=doc_title,
            language=language,
            owner_user_id=user.user_id,
        )
        session.add(document)
        version_no = 1
        supersedes_id = None
    else:
        current = await session.scalar(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == existing_document.id,
                DocumentVersion.effective_to.is_(None),
            )
            .with_for_update()
        )
        if current is None:
            raise ConflictError("Document has no current version")
        current.effective_to = datetime.now(UTC)
        version_no = current.version_no + 1
        supersedes_id = current.id
    version = DocumentVersion(
        id=version_id,
        tenant_id=user.tenant_id,
        document_id=resolved_document_id,
        version_no=version_no,
        content_sha256=digest,
        storage_key=key,
        mime_type=mime,
        effective_from=datetime.now(UTC),
        effective_to=None,
        supersedes_id=supersedes_id,
        parse_status=ParseStatus.PENDING.value,
    )
    session.add(version)
    job = IngestionJob(
        tenant_id=user.tenant_id,
        document_version_id=version_id,
        stage=IngestionStage.DOWNLOAD.value,
        status=JobStatus.PENDING.value,
    )
    session.add(job)
    await session.flush()

    # Commit before enqueue so the worker/sync path can see the rows.
    await session.commit()

    # Upload after the commit: a failure here leaves a job row we can mark failed,
    # whereas uploading first would strand an unreferenced object in the bucket on
    # any commit error. boto3 is synchronous, so keep it off the event loop.
    try:
        await anyio.to_thread.run_sync(storage.ensure_bucket)
        await anyio.to_thread.run_sync(
            lambda: storage.put_object(key=key, body=raw, content_type=mime)
        )
    except Exception as exc:
        # Reachable now that the tenant GUC survives the commit above (db.session
        # re-applies it on each transaction); previously this handler died inside
        # RLS and replaced the storage error with an opaque 500.
        job.status = JobStatus.FAILED.value
        job.error = f"upload failed: {exc}"[:2000]
        job.finished_at = datetime.now(UTC)
        version.parse_status = ParseStatus.FAILED.value
        await session.commit()
        raise

    # A failing pipeline must not turn an accepted upload into a 500: the bytes are
    # stored and the rows are committed, so the correct answer is still 202 with a
    # job the client can poll. The worker records the failure on the job row itself.
    try:
        dispatch = await enqueue_ingest(job.id)
    except Exception:
        logger.exception("ingest dispatch failed for job %s", job.id)
        dispatch = "failed"

    return UploadAccepted(
        document_id=resolved_document_id,
        version_id=version_id,
        job_id=job.id,
        dispatch=dispatch,
    )


@router.post("/{document_id}/versions", status_code=202, response_model=UploadAccepted)
async def upload_document_version(
    document_id: UUID,
    user: CuratorUser,
    limited: UploadRateLimited,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    file: Annotated[UploadFile, File()],
    collection_id: Annotated[UUID, Form()],
    title: Annotated[str | None, Form(max_length=300)] = None,
    language: Annotated[str, Form(pattern="^(en|pt)$")] = "en",
) -> UploadAccepted:
    return await upload_document(
        user=user,
        _limited=limited,
        session=session,
        file=file,
        collection_id=collection_id,
        title=title,
        language=language,
        document_id=document_id,
    )


@router.get("", response_model=DocumentPage)
async def list_documents(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    collection_id: UUID | None = None,
    limit: int = 50,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> DocumentPage:
    limit = page_limit(limit)
    stmt = select(Document).where(
        Document.tenant_id == user.tenant_id,
        Document.erased_at.is_(None),
    )
    if collection_id is not None:
        stmt = stmt.where(Document.collection_id == collection_id)
    stmt = await _readable_documents(session, user, stmt=stmt)
    stmt = apply_descending_cursor(
        stmt,
        created_column=Document.created_at,
        id_column=Document.id,
        cursor=cursor,
    )
    fetched = (
        await session.scalars(
            stmt.order_by(Document.created_at.desc(), Document.id.desc()).limit(limit + 1)
        )
    ).all()
    docs, next_cursor = page_rows(
        fetched,
        limit=limit,
        created_at=lambda row: row.created_at,
        item_id=lambda row: row.id,
    )

    # One query for every current version rather than one per document: at the
    # 200-document ceiling this was 201 round trips.
    current_by_doc: dict[UUID, UUID] = {}
    if docs:
        rows = await session.execute(
            select(DocumentVersion.document_id, DocumentVersion.id).where(
                DocumentVersion.document_id.in_([d.id for d in docs]),
                DocumentVersion.effective_to.is_(None),
            )
        )
        current_by_doc = {doc_id: version_id for doc_id, version_id in rows.all()}

    data: list[DocumentOut] = []
    for doc in docs:
        data.append(
            DocumentOut(
                id=doc.id,
                collection_id=doc.collection_id,
                title=doc.title,
                language=doc.language,
                archived_at=doc.archived_at,
                created_at=doc.created_at,
                current_version_id=current_by_doc.get(doc.id),
            )
        )
    return DocumentPage(data=data, next_cursor=next_cursor)


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentOut:
    stmt = select(Document).where(
        Document.id == document_id,
        Document.tenant_id == user.tenant_id,
        Document.erased_at.is_(None),
    )
    doc = await session.scalar(await _readable_documents(session, user, stmt=stmt))
    if doc is None:
        raise NotFoundError(f"No document {document_id}")
    current = await session.scalar(
        select(DocumentVersion.id).where(
            DocumentVersion.document_id == doc.id,
            DocumentVersion.effective_to.is_(None),
        )
    )
    return DocumentOut(
        id=doc.id,
        collection_id=doc.collection_id,
        title=doc.title,
        language=doc.language,
        archived_at=doc.archived_at,
        created_at=doc.created_at,
        current_version_id=current,
    )


@router.get("/{document_id}/versions", response_model=VersionPage)
async def list_document_versions(
    document_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = 200,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> VersionPage:
    limit = page_limit(limit)
    stmt = select(Document).where(
        Document.id == document_id,
        Document.tenant_id == user.tenant_id,
        Document.erased_at.is_(None),
    )
    if await session.scalar(await _readable_documents(session, user, stmt=stmt)) is None:
        raise NotFoundError(f"No document {document_id}")
    version_stmt = apply_descending_cursor(
        select(DocumentVersion).where(DocumentVersion.document_id == document_id),
        created_column=DocumentVersion.created_at,
        id_column=DocumentVersion.id,
        cursor=cursor,
    )
    fetched = (
        await session.scalars(
            version_stmt.order_by(
                DocumentVersion.created_at.desc(), DocumentVersion.id.desc()
            ).limit(limit + 1)
        )
    ).all()
    versions, next_cursor = page_rows(
        fetched,
        limit=limit,
        created_at=lambda row: row.created_at,
        item_id=lambda row: row.id,
    )
    return VersionPage(
        data=[
            VersionOut(
                id=version.id,
                version_no=version.version_no,
                content_sha256=version.content_sha256,
                effective_from=version.effective_from,
                effective_to=version.effective_to,
                parse_status=version.parse_status,
            )
            for version in versions
        ],
        next_cursor=next_cursor,
    )


@router.get("/{document_id}/jobs", response_model=JobPage)
async def list_document_jobs(
    document_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = 200,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> JobPage:
    limit = page_limit(limit)
    stmt = select(Document).where(
        Document.id == document_id,
        Document.tenant_id == user.tenant_id,
    )
    doc = await session.scalar(await _readable_documents(session, user, stmt=stmt))
    if doc is None:
        raise NotFoundError(f"No document {document_id}")
    version_ids = (
        await session.scalars(
            select(DocumentVersion.id).where(DocumentVersion.document_id == document_id)
        )
    ).all()
    job_stmt = apply_descending_cursor(
        select(IngestionJob).where(IngestionJob.document_version_id.in_(version_ids)),
        created_column=IngestionJob.created_at,
        id_column=IngestionJob.id,
        cursor=cursor,
    )
    fetched = (
        await session.scalars(
            job_stmt.order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc()).limit(
                limit + 1
            )
        )
    ).all()
    jobs, next_cursor = page_rows(
        fetched,
        limit=limit,
        created_at=lambda row: row.created_at,
        item_id=lambda row: row.id,
    )
    return JobPage(
        data=[
            JobOut(
                id=j.id,
                document_version_id=j.document_version_id,
                stage=j.stage,
                status=j.status,
                attempts=j.attempts,
                error=j.error,
                started_at=j.started_at,
                finished_at=j.finished_at,
                created_at=j.created_at,
            )
            for j in jobs
        ],
        next_cursor=next_cursor,
    )


@router.post("/{document_id}/archive", response_model=DocumentOut)
async def archive_document(
    document_id: UUID,
    user: CuratorUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentOut:
    stmt = select(Document).where(
        Document.id == document_id,
        Document.tenant_id == user.tenant_id,
    )
    doc = await session.scalar(await _readable_documents(session, user, stmt=stmt))
    if doc is None:
        raise NotFoundError(f"No document {document_id}")
    await _require_collection_write(session, user, doc.collection_id)
    if doc.archived_at is None:
        doc.archived_at = datetime.now(UTC)
        await session.flush()
    current = await session.scalar(
        select(DocumentVersion.id).where(
            DocumentVersion.document_id == doc.id, DocumentVersion.effective_to.is_(None)
        )
    )
    return DocumentOut(
        id=doc.id,
        collection_id=doc.collection_id,
        title=doc.title,
        language=doc.language,
        archived_at=doc.archived_at,
        created_at=doc.created_at,
        current_version_id=current,
    )


@router.post("/{document_id}/unarchive", response_model=DocumentOut)
async def unarchive_document(
    document_id: UUID,
    user: CuratorUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentOut:
    stmt = select(Document).where(
        Document.id == document_id,
        Document.tenant_id == user.tenant_id,
    )
    doc = await session.scalar(await _readable_documents(session, user, stmt=stmt))
    if doc is None:
        raise NotFoundError(f"No document {document_id}")
    await _require_collection_write(session, user, doc.collection_id)
    doc.archived_at = None
    await session.flush()
    current = await session.scalar(
        select(DocumentVersion.id).where(
            DocumentVersion.document_id == doc.id, DocumentVersion.effective_to.is_(None)
        )
    )
    return DocumentOut(
        id=doc.id,
        collection_id=doc.collection_id,
        title=doc.title,
        language=doc.language,
        archived_at=doc.archived_at,
        created_at=doc.created_at,
        current_version_id=current,
    )


@router.delete("/{document_id}")
async def delete_document(document_id: UUID, user: CurrentUser) -> object:
    del document_id, user
    raise HTTPException(
        status_code=405,
        detail=(
            "Hard delete is not offered. Use POST /api/v1/documents/{id}/archive "
            "or POST /api/v1/admin/documents/{id}/erase."
        ),
        headers={"Allow": "GET, POST"},
    )
