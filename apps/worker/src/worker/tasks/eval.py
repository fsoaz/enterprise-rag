"""Asynchronous evaluation execution with persisted progress and fail-closed results."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID

from evals.harness.metrics import (
    deduplicate_retrieved,
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import EvalDataset, EvalItem, EvalResult, EvalRun, User
from db.session import set_tenant_context
from retrieval.pipeline import retrieve
from worker.celery_app import celery_app


def _database_url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def _async_url(value: str) -> str:
    if value.startswith("postgresql+psycopg://"):
        return value.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


async def _resolve_run(run_id: UUID) -> tuple[UUID, UUID]:
    """Resolve tenant and dataset under BYPASSRLS before opening the app session."""
    engine = create_async_engine(_async_url(_database_url("DATABASE_URL_MIGRATE")))
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT set_config('app.current_tenant', '', false)"))
            row = await connection.execute(
                select(EvalRun.tenant_id, EvalRun.dataset_id).where(EvalRun.id == run_id)
            )
            values = row.one_or_none()
            if values is None:
                raise LookupError(f"evaluation run not found: {run_id}")
            return UUID(str(values[0])), UUID(str(values[1]))
    finally:
        await engine.dispose()


async def _set_run_state(
    run: EvalRun,
    session: AsyncSession,
    *,
    status: str,
    progress: int,
    error: str | None = None,
) -> None:
    run.params = {
        **(run.params or {}),
        "status": status,
        "progress": max(0, min(100, progress)),
        **({"error": error} if error else {}),
    }
    if status in {"complete", "incomplete", "failed"}:
        run.finished_at = datetime.now(UTC)
    await session.flush()


async def run_evaluation(run_id: UUID) -> None:
    tenant_id, dataset_id = await _resolve_run(run_id)
    engine = create_async_engine(_async_url(_database_url("DATABASE_URL")), pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                run = await session.scalar(
                    select(EvalRun).where(
                        EvalRun.id == run_id,
                        EvalRun.tenant_id == tenant_id,
                        EvalRun.dataset_id == dataset_id,
                    )
                )
                dataset = await session.scalar(
                    select(EvalDataset).where(
                        EvalDataset.id == dataset_id,
                        EvalDataset.tenant_id == tenant_id,
                    )
                )
                if run is None or dataset is None:
                    raise LookupError(f"evaluation run or dataset not found: {run_id}")
                items = (
                    await session.scalars(
                        select(EvalItem)
                        .where(EvalItem.dataset_id == dataset_id, EvalItem.tenant_id == tenant_id)
                        .order_by(EvalItem.created_at, EvalItem.id)
                    )
                ).all()
                await _set_run_state(run, session, status="running", progress=0)

            failures = 0
            for index, item in enumerate(items, 1):
                async with session.begin():
                    await set_tenant_context(session, tenant_id)
                    run = await session.scalar(
                        select(EvalRun).where(EvalRun.id == run_id, EvalRun.tenant_id == tenant_id)
                    )
                    if run is None:
                        raise LookupError(f"evaluation run disappeared: {run_id}")
                    try:
                        user_id = item.acting_user_id
                        if user_id is None:
                            user_id = await session.scalar(
                                select(User.id).where(
                                    User.tenant_id == tenant_id,
                                    User.external_subject.endswith("-admin"),
                                )
                            )
                        if user_id is None:
                            raise LookupError(f"no acting user for evaluation item {item.id}")
                        retrieval = await retrieve(
                            session,
                            tenant_id=tenant_id,
                            user_id=user_id,
                            query=item.question,
                            strategy=run.strategy,
                            as_of=item.as_of,
                        )
                        retrieved = deduplicate_retrieved(
                            [str(hit.chunk_id) for hit in retrieval.hits]
                        )
                        gold = [str(chunk_id) for chunk_id in (item.gold_chunk_ids or [])]
                        metrics = {
                            "recall@10": recall_at_k(retrieved, gold, 10),
                            "precision@10": precision_at_k(retrieved, gold, 10),
                            "nDCG@10": ndcg_at_k(retrieved, gold, 10),
                            "MRR@10": mrr_at_k(retrieved, gold, 10),
                            "abstention_expected": item.should_abstain,
                            "incomplete": True,
                            "incomplete_reason": "answer generation is not wired into the worker",
                        }
                        session.add(
                            EvalResult(
                                tenant_id=tenant_id,
                                run_id=run_id,
                                item_id=item.id,
                                retrieved_chunk_ids=[UUID(chunk_id) for chunk_id in retrieved]
                                or None,
                                metrics=metrics,
                                verdict="incomplete",
                            )
                        )
                    except Exception as exc:
                        failures += 1
                        session.add(
                            EvalResult(
                                tenant_id=tenant_id,
                                run_id=run_id,
                                item_id=item.id,
                                metrics={
                                    "incomplete": True,
                                    "error": f"{type(exc).__name__}: {exc}",
                                },
                                verdict="incomplete",
                            )
                        )
                    await _set_run_state(
                        run,
                        session,
                        status="running",
                        progress=int(index * 100 / max(1, len(items))),
                    )

            async with session.begin():
                await set_tenant_context(session, tenant_id)
                run = await session.scalar(
                    select(EvalRun).where(EvalRun.id == run_id, EvalRun.tenant_id == tenant_id)
                )
                if run is not None:
                    await _set_run_state(
                        run,
                        session,
                        status="incomplete",
                        progress=100,
                        error=(
                            f"{failures} item(s) failed"
                            if failures
                            else "answer generation unavailable"
                        ),
                    )
    except Exception:
        # A task retry can re-enter safely: item results are scoped to this run and
        # state remains explicit. The exception is re-raised for Celery observability.
        raise
    finally:
        await engine.dispose()


@celery_app.task(
    name="worker.tasks.eval.run_eval",
    bind=False,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)  # type: ignore[untyped-decorator]
def run_eval(run_id: str) -> None:
    asyncio.run(run_evaluation(UUID(run_id)))
