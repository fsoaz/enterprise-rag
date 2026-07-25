from __future__ import annotations

from worker.celery_app import celery_app


@celery_app.task(name="worker.noop")  # type: ignore[untyped-decorator]
def noop() -> dict[str, str]:
    """Prove broker wiring; replaced by real ingest tasks in Phase 1."""
    return {"status": "ok"}
