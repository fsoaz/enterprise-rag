"""Tenant-admin evaluation dataset and run API.

Runs are persisted before dispatch so worker retries always recover tenant
context from the database row rather than accepting it from a task payload.
"""

from __future__ import annotations

import hashlib
import json
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
from evaluation.labels import resolve_labels
from evaluation.report import ComparisonError, build_report

router = APIRouter(prefix="/evals", tags=["evaluation"])


class EvalItemIn(BaseModel):
    model_config = {"extra": "forbid"}
    id: str | None = Field(default=None, min_length=1, max_length=200)
    slice: str | None = Field(default=None, min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=16_000)
    expected_answer_facts: list[str] = Field(default_factory=list, max_length=50)
    expected_facts: list[str] | None = Field(default=None, max_length=50)
    gold_chunk_ids: list[UUID | str] = Field(default_factory=list, max_length=50)
    must_exclude_chunk_ids: list[UUID | str] = Field(default_factory=list, max_length=50)
    language: str = Field(default="en", pattern="^(en|pt)$")
    as_of: Annotated[datetime | None, BeforeValidator(parse_as_of)] = None
    acting_user_id: UUID | None = None
    acting_user: str | None = Field(default=None, max_length=200)
    should_abstain: bool = False

    def model_post_init(self, __context: Any) -> None:
        if self.expected_facts is not None:
            if self.expected_answer_facts:
                raise ValueError("use only expected_answer_facts or expected_facts")
            self.expected_answer_facts = self.expected_facts
        if set(self.gold_chunk_ids).intersection(self.must_exclude_chunk_ids):
            raise ValueError("gold and excluded chunks must be disjoint")


class DatasetCreate(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    dataset_slice: str | None = Field(default=None, max_length=100)
    items: list[EvalItemIn] = Field(min_length=1, max_length=10_000)

    def model_post_init(self, __context: Any) -> None:
        for item in self.items:
            if item.gold_chunk_ids and item.should_abstain:
                raise ValueError("abstaining items cannot declare gold chunks")
            if item.gold_chunk_ids and not item.expected_answer_facts:
                raise ValueError("supported items must declare expected answer facts")


class DatasetOut(BaseModel):
    id: UUID
    name: str
    version: str
    dataset_slice: str | None
    item_count: int
    created_at: datetime
    content_sha256: str | None = None


class DatasetPage(BaseModel):
    data: list[DatasetOut]
    next_cursor: str | None


class ItemOut(BaseModel):
    id: UUID
    external_id: str
    slice: str
    question: str
    expected_answer_facts: list[Any]
    language: str
    gold_chunk_ids: list[UUID] | None
    gold_chunk_labels: list[str] | None
    as_of: datetime | None
    acting_user_id: UUID | None
    should_abstain: bool
    must_exclude_chunk_ids: list[UUID] | None
    must_exclude_chunk_labels: list[str] | None


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
    citations: list[dict[str, Any]] | None
    verdict: str | None
    cost_usd: str | None


class ResultPage(BaseModel):
    data: list[ResultOut]
    next_cursor: str | None


class ComparisonRunOut(BaseModel):
    id: UUID
    dataset_id: UUID
    strategy: str
    embedding_model: str
    reranker: str | None
    generator_model: str
    status: str
    params: dict[str, Any]


class ComparisonResponse(BaseModel):
    baseline_run_id: UUID
    runs: list[ComparisonRunOut]
    dataset: dict[str, Any]
    overall: dict[str, dict[str, dict[str, Any]]]
    by_slice: dict[str, dict[str, dict[str, dict[str, Any]]]]
    coverage: dict[str, Any]
    statistics: dict[str, Any]


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


def _split_sources(values: list[UUID | str]) -> tuple[list[UUID], list[str]]:
    ids: list[UUID] = []
    labels: list[str] = []
    for value in values:
        if isinstance(value, UUID):
            ids.append(value)
            continue
        try:
            ids.append(UUID(value))
        except ValueError:
            labels.append(value)
    return ids, labels


def _dataset_content_sha256(items: list[EvalItemIn]) -> str:
    """Hash the validated request content before resolving database identities."""
    serialized_items = []
    for item in items:
        serialized = item.model_dump(exclude_none=True, mode="json")
        if item.acting_user is not None:
            # The API resolves symbolic subjects to tenant-local UUIDs below;
            # those internal identities must not affect dataset compatibility.
            serialized.pop("acting_user_id", None)
        serialized_items.append(serialized)
    return hashlib.sha256(
        json.dumps(
            serialized_items,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


@router.post("/datasets", response_model=DatasetOut, status_code=201)
async def register_dataset(
    body: DatasetCreate,
    user: AclAdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DatasetOut:
    item_ids = [item.id or str(index) for index, item in enumerate(body.items)]
    if len(set(item_ids)) != len(item_ids):
        raise ConflictError("Dataset item ids must be unique")
    content_sha256 = _dataset_content_sha256(body.items)
    subjects = {item.acting_user for item in body.items if item.acting_user is not None}
    if any(item.acting_user is not None and item.acting_user_id is not None for item in body.items):
        raise ConflictError("Provide acting_user or acting_user_id, not both")
    if subjects:
        subject_rows = (
            await session.scalars(
                select(User).where(
                    User.tenant_id == user.tenant_id,
                    User.external_subject.in_(subjects),
                )
            )
        ).all()
        subject_map = {row.external_subject: row.id for row in subject_rows}
        if set(subject_map) != subjects:
            raise ConflictError("Every acting user must belong to the current tenant")
        for item in body.items:
            if item.acting_user is not None:
                item.acting_user_id = subject_map[item.acting_user]

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
    source_ids: set[UUID] = set()
    source_labels: set[str] = set()
    for item in body.items:
        item_gold_ids, item_gold_labels = _split_sources(item.gold_chunk_ids)
        item_excluded_ids, item_excluded_labels = _split_sources(item.must_exclude_chunk_ids)
        source_ids.update((*item_gold_ids, *item_excluded_ids))
        source_labels.update((*item_gold_labels, *item_excluded_labels))
    if source_labels:
        resolved_labels = await resolve_labels(
            session, tenant_id=user.tenant_id, labels=source_labels
        )
        missing = source_labels - resolved_labels.keys()
        if missing:
            raise ConflictError(f"Unknown evaluation source labels: {sorted(missing)}")
        label_versions = [resolved_labels[label] for label in source_labels]
        source_ids.update(
            (
                await session.scalars(
                    select(Chunk.id).where(
                        Chunk.tenant_id == user.tenant_id,
                        Chunk.document_version_id.in_(label_versions),
                    )
                )
            ).all()
        )
    gold_chunks = source_ids
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
        content_sha256=content_sha256,
    )
    session.add(dataset)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(
            "An evaluation dataset with this name and version already exists"
        ) from exc
    for item, external_id in zip(body.items, item_ids, strict=True):
        gold_ids, gold_labels = _split_sources(item.gold_chunk_ids)
        excluded_ids, excluded_labels = _split_sources(item.must_exclude_chunk_ids)
        session.add(
            EvalItem(
                tenant_id=user.tenant_id,
                dataset_id=dataset.id,
                external_id=external_id,
                item_slice=item.slice or body.dataset_slice or "default",
                question=item.question,
                language=item.language,
                expected_facts=item.expected_answer_facts,
                gold_chunk_ids=gold_ids or None,
                gold_chunk_labels=gold_labels or None,
                must_exclude_chunk_ids=excluded_ids or None,
                must_exclude_chunk_labels=excluded_labels or None,
                as_of=item.as_of,
                acting_user_id=item.acting_user_id,
                should_abstain=item.should_abstain,
            )
        )
    # Dependency cleanup may run after a client starts its next request.
    # Publish the dataset ID only once its items are visible on other connections.
    await session.commit()
    return DatasetOut(
        id=dataset.id,
        name=dataset.name,
        version=dataset.version,
        dataset_slice=dataset.dataset_slice,
        item_count=len(body.items),
        created_at=dataset.created_at,
        content_sha256=dataset.content_sha256,
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
                content_sha256=row.content_sha256,
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
                external_id=row.external_id,
                slice=row.item_slice,
                question=row.question,
                expected_answer_facts=list(row.expected_facts or []),
                language=row.language,
                gold_chunk_ids=row.gold_chunk_ids,
                gold_chunk_labels=row.gold_chunk_labels,
                as_of=row.as_of,
                acting_user_id=row.acting_user_id,
                should_abstain=row.should_abstain,
                must_exclude_chunk_ids=row.must_exclude_chunk_ids,
                must_exclude_chunk_labels=row.must_exclude_chunk_labels,
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
    run_params = dict(body.params)
    immutable_config = {
        "embedding_model_name": body.embedding_model,
        "reranker_identity": body.reranker,
    }
    for key, expected in immutable_config.items():
        if key in run_params and run_params[key] != expected:
            raise ConflictError(f"Run parameter {key} must match the run model identity")
        run_params[key] = expected
    run = EvalRun(
        tenant_id=user.tenant_id,
        dataset_id=dataset.id,
        strategy=body.strategy,
        embedding_model=body.embedding_model,
        reranker=body.reranker,
        generator_model=body.generator_model,
        params={**run_params, "status": "queued", "progress": 0},
        judge_prompt_hash=body.judge_prompt_hash,
        started_at=datetime.now(UTC),
    )
    session.add(run)
    # Workers use a separate connection and must see the queued run before publication.
    await session.commit()
    try:
        _dispatch_run(run.id)
    except Exception as exc:
        run.params = {**run.params, "status": "failed", "error": str(exc)}
        await session.commit()
    return _run_out(run)


async def _comparison_report(
    ids: list[UUID], user: AclAdminUser, session: AsyncSession
) -> dict[str, Any]:
    if len(ids) < 2:
        raise ConflictError("At least two run ids are required for comparison")
    if len(set(ids)) != len(ids):
        raise ConflictError("Comparison run ids must be unique")
    rows = (
        await session.scalars(
            select(EvalRun).where(EvalRun.id.in_(ids), EvalRun.tenant_id == user.tenant_id)
        )
    ).all()
    by_id = {row.id: row for row in rows}
    missing_ids = [str(run_id) for run_id in ids if run_id not in by_id]
    if missing_ids:
        raise NotFoundError(f"Evaluation run not found: {', '.join(missing_ids)}")
    ordered_runs = [by_id[run_id] for run_id in ids]
    dataset_ids = {run.dataset_id for run in ordered_runs}
    if len(dataset_ids) != 1:
        raise ConflictError("Runs use incompatible datasets")
    dataset_id = ordered_runs[0].dataset_id
    dataset = await session.scalar(
        select(EvalDataset).where(
            EvalDataset.id == dataset_id, EvalDataset.tenant_id == user.tenant_id
        )
    )
    if dataset is None:
        raise NotFoundError("Evaluation dataset not found")
    items = (
        await session.scalars(
            select(EvalItem)
            .where(EvalItem.dataset_id == dataset_id, EvalItem.tenant_id == user.tenant_id)
            .order_by(EvalItem.created_at, EvalItem.id)
        )
    ).all()
    result_rows = (
        await session.scalars(
            select(EvalResult)
            .where(
                EvalResult.run_id.in_(ids),
                EvalResult.tenant_id == user.tenant_id,
            )
            .order_by(EvalResult.created_at, EvalResult.id)
        )
    ).all()
    grouped: dict[str, list[EvalResult]] = {str(run_id): [] for run_id in ids}
    for result in result_rows:
        grouped[str(result.run_id)].append(result)
    try:
        report = build_report(
            ordered_runs,
            items,
            grouped,
            baseline_id=str(ids[0]),
        )
    except ComparisonError as exc:
        raise ConflictError(str(exc)) from exc
    report["dataset"].update(
        {
            "name": dataset.name,
            "version": dataset.version,
            "dataset_slice": dataset.dataset_slice,
            "content_sha256": dataset.content_sha256,
        }
    )
    return report


@router.get("/runs/compare", response_model=ComparisonResponse)
async def compare_runs_matrix(
    ids: Annotated[str, Query(min_length=1, max_length=2000)],
    user: AclAdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ComparisonResponse:
    try:
        run_ids = [UUID(value.strip()) for value in ids.split(",") if value.strip()]
    except ValueError as exc:
        raise ConflictError("ids must be a comma-separated list of UUIDs") from exc
    return ComparisonResponse(**(await _comparison_report(run_ids, user, session)))


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
                citations=row.citations,
                verdict=row.verdict,
                cost_usd=str(row.cost_usd) if row.cost_usd is not None else None,
            )
            for row in rows
        ],
        next_cursor=next_cursor,
    )
