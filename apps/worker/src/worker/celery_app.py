from __future__ import annotations

import os

from celery import Celery
from pydantic_settings import BaseSettings, SettingsConfigDict

from observability.logging import configure_logging


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    celery_broker_url: str = "redis://localhost:16379/1"
    celery_result_backend: str = "redis://localhost:16379/2"


settings = WorkerSettings()

configure_logging(os.environ.get("LOG_LEVEL", "INFO"))

celery_app = Celery(
    "enterprise_rag_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["worker.tasks.noop", "worker.tasks.ingest", "worker.tasks.eval"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
