"""Documents API — upload, list, archive (no hard delete)."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.auth import AuthUser, CuratorUser, CurrentUser
from api.deps.db import get_db_session
from api.services import storage
from api.services.ingest import enqueue_ingest
from api.services.problems import problem
from db.models import Collection, Document, DocumentVersion, IngestionJob
from domain.errors import (
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from domain.types import AclPermission, IngestionStage, JobStatus, ParseStatus
from retrieval.acl import document_acl_predicate, resolve_acl

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
    """
    resolution = await resolve_acl(
        session,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        permission=AclPermission.READ,
    )
    return stmt.where(document_acl_predicate(resolution))


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


class UploadAccepted(BaseModel):
    document_id: UUID
    version_id: UUID
    job_id: UUID
    dispatch: str


def _guess_mime(filename: str, content_type: str | None) -> str:
    """Resolve the MIME type, preferring the extension over a generic browser guess.

    Browsers send ``application/octet-stream`` for .md on many platforms, so the
    extension is consulted whenever the declared type is absent, generic, or not
    something the ingest pipeline can parse.
    """
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith((".md", ".markdown")):
        return "text/markdown"
    if lower.endswith(".txt"):
        return "text/plain"
    if content_type and content_type != "application/octet-stream":
        return content_type
    return content_type or "application/octet-stream"


@router.post("", status_code=202, response_model=UploadAccepted)
async def upload_document(
    user: CuratorUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    file: Annotated[UploadFile, File()],
    collection_id: Annotated[UUID, Form()],
    title: Annotated[str | None, Form()] = None,
    language: Annotated[str, Form()] = "en",
) -> UploadAccepted:
    collection = await session.scalar(
        select(Collection).where(
            Collection.id == collection_id,
            Collection.tenant_id == user.tenant_id,
        )
    )
    if collection is None:
        raise NotFoundError(f"No collection {collection_id}")

    # Holding a curator role is not enough — the caller must also hold write on
    # this specific collection, otherwise a steward scoped to one collection could
    # inject documents into another (including one they cannot read back).
    write_acl = await resolve_acl(
        session,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        permission=AclPermission.WRITE,
    )
    if not write_acl.subjects.is_admin and collection_id not in write_acl.allowed_collection_ids:
        raise PermissionDeniedError(f"No write permission on collection {collection_id}")

    raw = await _read_capped(file, max_upload_bytes())
    if not raw:
        raise ValidationError("Uploaded file has no content")

    digest = hashlib.sha256(raw).hexdigest()
    filename = file.filename or "upload.bin"
    mime = _guess_mime(filename, file.content_type)
    if mime not in ALLOWED_MIME_TYPES:
        raise UnsupportedMediaTypeError(mime)
    doc_title = title or filename

    document_id = uuid4()
    version_id = uuid4()
    key = storage.storage_key(
        tenant_id=user.tenant_id,
        document_id=document_id,
        version_id=version_id,
        filename=filename,
    )

    document = Document(
        id=document_id,
        tenant_id=user.tenant_id,
        collection_id=collection_id,
        title=doc_title,
        language=language,
        owner_user_id=user.user_id,
    )
    session.add(document)
    version = DocumentVersion(
        id=version_id,
        tenant_id=user.tenant_id,
        document_id=document_id,
        version_no=1,
        content_sha256=digest,
        storage_key=key,
        mime_type=mime,
        effective_from=datetime.now(UTC),
        effective_to=None,
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
        job.status = JobStatus.FAILED.value
        job.error = f"upload failed: {exc}"[:2000]
        job.finished_at = datetime.now(UTC)
        version.parse_status = ParseStatus.FAILED.value
        await session.commit()
        raise

    dispatch = await enqueue_ingest(job.id)

    return UploadAccepted(
        document_id=document_id,
        version_id=version_id,
        job_id=job.id,
        dispatch=dispatch,
    )


@router.get("", response_model=dict)
async def list_documents(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    collection_id: UUID | None = None,
    limit: int = 50,
) -> dict[str, object]:
    limit = min(max(limit, 1), 200)
    stmt = select(Document).where(
        Document.tenant_id == user.tenant_id,
        Document.erased_at.is_(None),
    )
    if collection_id is not None:
        stmt = stmt.where(Document.collection_id == collection_id)
    stmt = await _readable_documents(session, user, stmt=stmt)
    stmt = stmt.order_by(Document.created_at.desc()).limit(limit)
    docs = (await session.scalars(stmt)).all()

    data: list[DocumentOut] = []
    for doc in docs:
        current = await session.scalar(
            select(DocumentVersion.id).where(
                DocumentVersion.document_id == doc.id,
                DocumentVersion.effective_to.is_(None),
            )
        )
        data.append(
            DocumentOut(
                id=doc.id,
                collection_id=doc.collection_id,
                title=doc.title,
                language=doc.language,
                archived_at=doc.archived_at,
                created_at=doc.created_at,
                current_version_id=current,
            )
        )
    return {"data": data, "next_cursor": None}


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


@router.get("/{document_id}/jobs", response_model=dict)
async def list_document_jobs(
    document_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
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
    jobs = (
        await session.scalars(
            select(IngestionJob)
            .where(IngestionJob.document_version_id.in_(version_ids))
            .order_by(IngestionJob.created_at.desc())
        )
    ).all()
    return {
        "data": [
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
        "next_cursor": None,
    }


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
    if doc.archived_at is None:
        doc.archived_at = datetime.now(UTC)
        await session.flush()
    return DocumentOut(
        id=doc.id,
        collection_id=doc.collection_id,
        title=doc.title,
        language=doc.language,
        archived_at=doc.archived_at,
        created_at=doc.created_at,
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
    doc.archived_at = None
    await session.flush()
    return DocumentOut(
        id=doc.id,
        collection_id=doc.collection_id,
        title=doc.title,
        language=doc.language,
        archived_at=doc.archived_at,
        created_at=doc.created_at,
    )


@router.delete("/{document_id}")
async def delete_document(document_id: UUID, user: CurrentUser) -> object:
    del document_id, user
    return problem(
        status=405,
        title="Method Not Allowed",
        detail=(
            "Hard delete is not offered. Use POST /api/v1/documents/{id}/archive "
            "or POST /api/v1/admin/documents/{id}/erase."
        ),
        type_slug="method-not-allowed",
        extra={
            "allow": ["GET", "POST"],
            "alternatives": {
                "archive": "/api/v1/documents/{id}/archive",
                "erase": "/api/v1/admin/documents/{id}/erase",
            },
        },
    )
