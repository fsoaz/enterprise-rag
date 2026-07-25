"""Celery ingest task: download → parse → chunk → embed → index.

Tenant context is taken from the job row in the database (architecture § 4.2),
never trusted from the Celery payload as an authorization source.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID

import boto3
from botocore.client import BaseClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Chunk, ChunkEmbedding, DocumentVersion, IngestionJob
from db.session import set_tenant_context
from domain.types import IngestionStage, JobStatus, ParseStatus
from worker.celery_app import celery_app
from worker.pipeline.chunk import chunk_document
from worker.pipeline.embed import embed_passages, embedding_model_meta
from worker.pipeline.index import index_chunks_search_vectors
from worker.pipeline.parse import parse_bytes


def _app_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        msg = "DATABASE_URL is not set"
        raise RuntimeError(msg)
    return url


def _bypass_database_url() -> str:
    """BYPASSRLS (or migrate) URL used only to resolve job → tenant_id."""
    url = (
        os.environ.get("DATABASE_URL_MIGRATE")
        or os.environ.get("DATABASE_URL_MAINT")
        or os.environ.get("DATABASE_URL")
    )
    if not url:
        msg = "DATABASE_URL_MIGRATE / DATABASE_URL must be set"
        raise RuntimeError(msg)
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _s3_client() -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "minioadmin"),
        region_name=os.environ.get("S3_REGION", "us-east-1"),
    )


def _s3_bucket() -> str:
    return os.environ.get("S3_BUCKET", "enterprise-rag")


async def _resolve_tenant_id(job_id: UUID) -> UUID:
    engine = create_async_engine(_bypass_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            # Clear tenant GUC so migrate role can read any job row.
            await conn.execute(text("SELECT set_config('app.current_tenant', '', false)"))
            row = await conn.execute(
                text("SELECT tenant_id FROM ingestion_jobs WHERE id = :id"),
                {"id": job_id},
            )
            tenant_id = row.scalar_one_or_none()
            if tenant_id is None:
                msg = f"ingestion job not found: {job_id}"
                raise LookupError(msg)
            return UUID(str(tenant_id))
    finally:
        await engine.dispose()


async def _set_job_stage(
    session: AsyncSession,
    job: IngestionJob,
    *,
    stage: IngestionStage,
    status: JobStatus = JobStatus.RUNNING,
    error: str | None = None,
) -> None:
    job.stage = stage.value
    job.status = status.value
    job.error = error
    if status == JobStatus.RUNNING and job.started_at is None:
        job.started_at = datetime.now(UTC)
    if status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
        job.finished_at = datetime.now(UTC)
    await session.flush()


async def run_ingest_job(job_id: UUID) -> None:
    """Run the full ingest pipeline for a job. Safe to call from API (sync path)."""
    tenant_id = await _resolve_tenant_id(job_id)
    engine = create_async_engine(_app_database_url(), pool_pre_ping=True)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    try:
        async with factory() as session, session.begin():
            await set_tenant_context(session, tenant_id)
            job = await session.scalar(select(IngestionJob).where(IngestionJob.id == job_id))
            if job is None:
                msg = f"ingestion job not found under tenant: {job_id}"
                raise LookupError(msg)
            # DB row is authoritative — payload was only used as a pointer.
            if job.tenant_id != tenant_id:
                msg = "job tenant mismatch"
                raise RuntimeError(msg)

            job.attempts = int(job.attempts or 0) + 1
            await _set_job_stage(session, job, stage=IngestionStage.DOWNLOAD)

            version = await session.scalar(
                select(DocumentVersion).where(DocumentVersion.id == job.document_version_id)
            )
            if version is None:
                await _set_job_stage(
                    session,
                    job,
                    stage=IngestionStage.DOWNLOAD,
                    status=JobStatus.FAILED,
                    error="document version not found",
                )
                return

            version.parse_status = ParseStatus.RUNNING.value
            await session.flush()

            try:
                # --- download ---
                client = _s3_client()
                obj = client.get_object(Bucket=_s3_bucket(), Key=version.storage_key)
                raw: bytes = obj["Body"].read()

                # --- parse ---
                await _set_job_stage(session, job, stage=IngestionStage.PARSE)
                parsed = parse_bytes(raw, mime_type=version.mime_type)
                version.page_count = len(parsed.pages) or None

                # --- chunk ---
                await _set_job_stage(session, job, stage=IngestionStage.CHUNK)
                text_chunks = chunk_document(parsed)
                # Replace any prior chunks for this version (re-ingest).
                existing = (
                    await session.scalars(
                        select(Chunk).where(Chunk.document_version_id == version.id)
                    )
                ).all()
                for old in existing:
                    await session.delete(old)
                await session.flush()

                chunk_rows: list[Chunk] = []
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
                    chunk_rows.append(row)
                await session.flush()

                # --- embed ---
                await _set_job_stage(session, job, stage=IngestionStage.EMBED)
                model_name, model_version = embedding_model_meta()
                bodies = [c.body for c in chunk_rows]
                # Batch embed to keep inference payloads bounded.
                batch_size = 32
                vectors: list[list[float]] = []
                for i in range(0, len(bodies), batch_size):
                    vectors.extend(await embed_passages(bodies[i : i + batch_size]))

                for chunk_row, vector in zip(chunk_rows, vectors, strict=True):
                    session.add(
                        ChunkEmbedding(
                            chunk_id=chunk_row.id,
                            tenant_id=tenant_id,
                            model_name=model_name,
                            model_version=model_version,
                            embedding=vector,
                        )
                    )
                await session.flush()

                # --- index (FTS) ---
                await _set_job_stage(session, job, stage=IngestionStage.INDEX)
                await index_chunks_search_vectors(
                    session,
                    chunk_ids=[c.id for c in chunk_rows],
                    tenant_id=tenant_id,
                )

                version.parse_status = ParseStatus.SUCCEEDED.value
                await _set_job_stage(
                    session, job, stage=IngestionStage.INDEX, status=JobStatus.SUCCEEDED
                )
            except Exception as exc:
                version.parse_status = ParseStatus.FAILED.value
                await _set_job_stage(
                    session,
                    job,
                    stage=IngestionStage(job.stage),
                    status=JobStatus.FAILED,
                    error=str(exc)[:2000],
                )
                raise
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="worker.tasks.ingest.ingest_document_version",
    bind=False,
)
def ingest_document_version(job_id: str) -> None:
    """Celery entrypoint — payload is job_id only (tenant from DB)."""
    asyncio.run(run_ingest_job(UUID(job_id)))
