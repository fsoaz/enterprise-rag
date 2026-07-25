"""Enqueue ingest jobs; fall back to in-process pipeline when Celery is unavailable."""

from __future__ import annotations

import asyncio
import logging
import os
from uuid import UUID

import anyio

logger = logging.getLogger(__name__)


def _ingest_sync_enabled() -> bool:
    return os.environ.get("INGEST_SYNC", "").lower() in {"1", "true", "yes"}


async def enqueue_ingest(job_id: UUID) -> str:
    """Enqueue Celery task or run inline. Returns ``celery`` or ``sync``."""
    if _ingest_sync_enabled():
        await _run_sync(job_id)
        return "sync"

    try:
        from worker.tasks.ingest import ingest_document_version

        # kombu's publish path is synchronous and blocks on a stalled broker.
        await anyio.to_thread.run_sync(lambda: ingest_document_version.delay(str(job_id)))
        return "celery"
    except Exception as exc:
        logger.warning("celery unavailable (%s); running ingest inline", exc)
        await _run_sync(job_id)
        return "sync"


async def _run_sync(job_id: UUID) -> None:
    """Run the pipeline inline (demo mode) without blocking the event loop.

    ``run_ingest_job`` builds its own engine and session, so it is safe to drive
    from a fresh loop on a worker thread. Keeping it off the request loop means a
    slow parse/embed does not stall every other in-flight request.
    """
    from worker.tasks.ingest import run_ingest_job

    await anyio.to_thread.run_sync(lambda: asyncio.run(run_ingest_job(job_id)))
