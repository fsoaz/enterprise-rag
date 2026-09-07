"""Tenant-admin evaluation dataset and run API.

Runs are persisted before dispatch so worker retries always recover tenant
context from the database row rather than accepting it from a task payload.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from celery import Celery
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.auth import AclAdminUser
from api.deps.db import get_db_session
from api.pagination import apply_descending_cursor, page_limit, page_rows
from db.models import Chunk, EvalDataset, EvalItem, EvalResult, EvalRun, User
from domain.errors import ConflictError, NotFoundError
from domain.temporal import parse_as_of

router = APIRouter(prefix="/evals", tags=["evaluation"])


class EvalItemIn(BaseModel):
    question: str = Field(min_length=1, max_length=16_000)
    expected_facts: list[str] = Field(default_factory=list, max_length=50)
    gold_chunk_ids: list[UUID] = Field(default_factory=list, max_length=50)
    as_of: Annotated[datetime | None, BeforeValidator(parse_as_of)] = None
    acting_user_id: UUID | None = None
    should_abstain: bool = False


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    dataset_slice: str | None = Field(default=None, max_length=100)
    items: list[EvalItemIn] = Field(min_length=1, max_length=10_000)


class DatasetOut(BaseModel):
    id: UUID
    name: str
    version: str
    dataset_slice: str | None
    item_count: int
    created_at: datetime


class DatasetPage(BaseModel):
    data: list[DatasetOut]
    next_cursor: str | None


class ItemOut(BaseModel):
    id: UUID
    question: str
    expected_facts: list[Any]
    gold_chunk_ids: list[UUID] | None
    as_of: datetime | None
    acting_user_id: UUID | None
    should_abstain: bool


class ItemPage(BaseModel):
    data: list[ItemOut]
    next_cursor: str | None


class RunCreate(BaseModel):
    dataset_id: UUID
    strategy: str = Field(min_length=1, max_length=100)
    embedding_model: str = Field(min_length=1, max_length=200)
    reranker: str | None = Field(default=None, max_length=200)
    generator_model: str = Field(min_length=1, max_length=200)
    params: dict[str, Any] = Field(default_factory=dict)
    judge_prompt_hash: str | None = Field(default=None, max_length=128)


class RunOut(BaseModel):
    id: UUID
    dataset_id: UUID
    status: str
    progress: int
    error: str | None
    strategy: str
    embedding_model: str
    reranker: str | None
    generator_model: str
    params: dict[str, Any]
    judge_prompt_hash: str | None
    started_at: datetime
    finished_at: datetime | None
    git_sha: str | None


class ResultOut(BaseModel):
    id: UUID
    item_id: UUID
    retrieved_chunk_ids: list[UUID] | None
    metrics: dict[str, Any]
    answer_text: str | None
    verdict: str | None
    cost_usd: str | None


class ResultPage(BaseModel):
    data: list[ResultOut]
    next_cursor: str | None


def _run_out(run: EvalRun) -> RunOut:
    params = dict(run.params or {})
    return RunOut(
        id=run.id,
        dataset_id=run.dataset_id,
        status=str(params.get("status", "queued" if run.finished_at is None else "complete")),
        progress=int(params.get("progress", 0)),
        error=str(params["error"]) if params.get("error") else None,
        strategy=run.strategy,
        embedding_model=run.embedding_model,
        reranker=run.reranker,
        generator_model=run.generator_model,
        params=params,
        judge_prompt_hash=run.judge_prompt_hash,
        started_at=run.started_at,
        finished_at=run.finished_at,
        git_sha=run.git_sha,
    )


@router.post("/datasets", response_model=DatasetOut, status_code=201)
async def register_dataset(
    body: DatasetCreate,
    user: AclAdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DatasetOut:
    acting_users = {item.acting_user_id for item in body.items if item.acting_user_id is not None}
    if acting_users:
        valid_users = set(
            (
                await session.scalars(
                    select(User.id).where(
                        User.id.in_(acting_users), User.tenant_id == user.tenant_id
                    )
                )
            ).all()
        )
        if valid_users != acting_users:
            raise ConflictError("Every acting user must belong to the current tenant")
    gold_chunks = {chunk_id for item in body.items for chunk_id in item.gold_chunk_ids}
    if gold_chunks:
        valid_chunks = set(
            (
                await session.scalars(
                    select(Chunk.id).where(
                        Chunk.id.in_(gold_chunks), Chunk.tenant_id == user.tenant_id
                    )
                )
            ).all()
        )
        if valid_chunks != gold_chunks:
            raise ConflictError("Every gold chunk must belong to the current tenant")
    dataset = EvalDataset(
        tenant_id=user.tenant_id,
        name=body.name,
        version=body.version,
        dataset_slice=body.dataset_slice,
    )
    session.add(dataset)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(
            "An evaluation dataset with this name and version already exists"
        ) from exc
    for item in body.items:
        session.add(
            EvalItem(
                tenant_id=user.tenant_id,
                dataset_id=dataset.id,
                question=item.question,
                expected_facts=item.expected_facts,
                gold_chunk_ids=item.gold_chunk_ids or None,
                as_of=item.as_of,
                acting_user_id=item.acting_user_id,
                should_abstain=item.should_abstain,
            )
        )
    await session.flush()
    return DatasetOut(
        id=dataset.id,
        name=dataset.name,
        version=dataset.version,
        dataset_slice=dataset.dataset_slice,
        item_count=len(body.items),
        created_at=dataset.created_at,
    )


@router.get("/datasets", response_model=DatasetPage)
async def list_datasets(
    user: AclAdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = 200,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> DatasetPage:
    limit = page_limit(limit)
    stmt = (
        apply_descending_cursor(
            select(EvalDataset).where(EvalDataset.tenant_id == user.tenant_id),
            created_column=EvalDataset.created_at,
            id_column=EvalDataset.id,
            cursor=cursor,
        )
        .order_by(EvalDataset.created_at.desc(), EvalDataset.id.desc())
        .limit(limit + 1)
    )
    rows, next_cursor = page_rows(
        (await session.scalars(stmt)).all(),
        limit=limit,
        created_at=lambda row: row.created_at,
        item_id=lambda row: row.id,
    )
    count_rows = await session.execute(
        select(EvalItem.dataset_id, func.count(EvalItem.id))
        .where(EvalItem.dataset_id.in_([row.id for row in rows]))
        .group_by(EvalItem.dataset_id)
    )
    counts = {dataset_id: int(count) for dataset_id, count in count_rows.all()}
    return DatasetPage(
        data=[
            DatasetOut(
                id=row.id,
                name=row.name,
                version=row.version,
                dataset_slice=row.dataset_slice,
                item_count=int(counts.get(row.id, 0)),
                created_at=row.created_at,
            )
            for row in rows
        ],
        next_cursor=next_cursor,
    )


@router.get("/datasets/{dataset_id}/items", response_model=ItemPage)
async def list_items(
    dataset_id: UUID,
    user: AclAdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = 200,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> ItemPage:
    dataset = await session.scalar(
        select(EvalDataset).where(
            EvalDataset.id == dataset_id, EvalDataset.tenant_id == user.tenant_id
        )
    )
    if dataset is None:
        raise NotFoundError("Evaluation dataset not found")
    limit = page_limit(limit)
    stmt = (
        apply_descending_cursor(
            select(EvalItem).where(
                EvalItem.dataset_id == dataset_id, EvalItem.tenant_id == user.tenant_id
            ),
            created_column=EvalItem.created_at,
            id_column=EvalItem.id,
            cursor=cursor,
        )
        .order_by(EvalItem.created_at.desc(), EvalItem.id.desc())
        .limit(limit + 1)
    )
    rows, next_cursor = page_rows(
        (await session.scalars(stmt)).all(),
        limit=limit,
        created_at=lambda row: row.created_at,
        item_id=lambda row: row.id,
    )
    return ItemPage(
        data=[
            ItemOut(
                id=row.id,
                question=row.question,
                expected_facts=list(row.expected_facts or []),
                gold_chunk_ids=row.gold_chunk_ids,
                as_of=row.as_of,
                acting_user_id=row.acting_user_id,
                should_abstain=row.should_abstain,
            )
            for row in rows
        ],
        next_cursor=next_cursor,
    )


def _dispatch_run(run_id: UUID) -> None:
    app = Celery(
        "enterprise_rag_api",
        broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:16379/1"),
        backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:16379/2"),
    )
    app.send_task("worker.tasks.eval.run_eval", args=[str(run_id)])


@router.post("/runs", response_model=RunOut, status_code=202)
async def create_run(
    body: RunCreate,
    user: AclAdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RunOut:
    dataset = await session.scalar(
        select(EvalDataset).where(
            EvalDataset.id == body.dataset_id, EvalDataset.tenant_id == user.tenant_id
        )
    )
    if dataset is None:
        raise NotFoundError("Evaluation dataset not found")
    run = EvalRun(
        tenant_id=user.tenant_id,
        dataset_id=dataset.id,
        strategy=body.strategy,
        embedding_model=body.embedding_model,
        reranker=body.reranker,
        generator_model=body.generator_model,
        params={**body.params, "status": "queued", "progress": 0},
        judge_prompt_hash=body.judge_prompt_hash,
        started_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()
    try:
        _dispatch_run(run.id)
    except Exception as exc:
        run.params = {**run.params, "status": "failed", "error": str(exc)}
        await session.flush()
    return _run_out(run)


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(
    run_id: UUID,
    user: AclAdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RunOut:
    run = await session.scalar(
        select(EvalRun).where(EvalRun.id == run_id, EvalRun.tenant_id == user.tenant_id)
    )
    if run is None:
        raise NotFoundError("Evaluation run not found")
    return _run_out(run)


@router.get("/runs/{run_id}/results", response_model=ResultPage)
async def list_results(
    run_id: UUID,
    user: AclAdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = 200,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> ResultPage:
    run = await session.scalar(
        select(EvalRun).where(EvalRun.id == run_id, EvalRun.tenant_id == user.tenant_id)
    )
    if run is None:
        raise NotFoundError("Evaluation run not found")
    limit = page_limit(limit)
    stmt = (
        apply_descending_cursor(
            select(EvalResult).where(
                EvalResult.run_id == run_id, EvalResult.tenant_id == user.tenant_id
            ),
            created_column=EvalResult.created_at,
            id_column=EvalResult.id,
            cursor=cursor,
        )
        .order_by(EvalResult.created_at.desc(), EvalResult.id.desc())
        .limit(limit + 1)
    )
    rows, next_cursor = page_rows(
        (await session.scalars(stmt)).all(),
        limit=limit,
        created_at=lambda row: row.created_at,
        item_id=lambda row: row.id,
    )
    return ResultPage(
        data=[
            ResultOut(
                id=row.id,
                item_id=row.item_id,
                retrieved_chunk_ids=row.retrieved_chunk_ids,
                metrics=dict(row.metrics or {}),
                answer_text=row.answer_text,
                verdict=row.verdict,
                cost_usd=str(row.cost_usd) if row.cost_usd is not None else None,
            )
            for row in rows
        ],
        next_cursor=next_cursor,
    )


@router.get("/runs/{left_id}/compare/{right_id}")
async def compare_runs(
    left_id: UUID,
    right_id: UUID,
    user: AclAdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    runs = (
        await session.scalars(
            select(EvalRun).where(
                EvalRun.id.in_((left_id, right_id)), EvalRun.tenant_id == user.tenant_id
            )
        )
    ).all()
    if len(runs) != 2:
        raise NotFoundError("Evaluation run not found")
    left, right = sorted(runs, key=lambda run: 0 if run.id == left_id else 1)
    if left.dataset_id != right.dataset_id:
        raise ConflictError("Runs use incompatible datasets")
    return {
        "left_run_id": str(left.id),
        "right_run_id": str(right.id),
        "compatible": True,
        "left": dict(left.params or {}),
        "right": dict(right.params or {}),
    }
