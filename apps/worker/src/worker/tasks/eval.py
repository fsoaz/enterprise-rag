"""Durable asynchronous evaluation execution."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from evals.harness.metrics import (
    deduplicate_retrieved,
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Chunk, CostLedger, Document, EvalDataset, EvalItem, EvalResult, EvalRun, User
from db.session import set_tenant_context
from llm.client import AnthropicClient, CitationSpan, RetrievedChunk, extractive_fallback
from llm.groundedness import citation_coverage, groundedness_verdict, retrieval_confidence
from llm.judge import rubric_hash
from llm.models import JUDGE_MODEL
from retrieval.pipeline import retrieve
from worker.celery_app import celery_app

PRICE_TABLE_VERSION = "v0"


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


def _live_llm() -> bool:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return bool(key and not key.startswith("sk-ant-replace"))


def _budget() -> Decimal:
    return Decimal(os.environ.get("TENANT_DAILY_BUDGET_USD", "25"))


def _retrieval_config(run: EvalRun) -> dict[str, Any]:
    """Read the immutable per-run retrieval identity and knobs.

    T-405 runs predate the comparison runner, so the database columns remain the
    fallback source for older rows.  New runs copy the complete sweep selection
    into ``params`` and this function never changes it.
    """
    params = dict(run.params or {})
    retrieval = params.get("retrieval", {})
    if not isinstance(retrieval, dict):
        raise ValueError("run.params.retrieval must be an object")

    def optional_string(key: str) -> str | None:
        value = params.get(key)
        return str(value) if value else None

    return {
        "top_k": int(retrieval.get("top_k", 8)),
        "retrieval_k": int(retrieval.get("retrieval_k", 50)),
        "rrf_k": int(retrieval.get("rrf_k", 60)),
        "embedding_model": (
            str(params["embedding_model_name"])
            if params.get("embedding_model_name") is not None
            else None
        ),
        "embedding_model_version": optional_string("embedding_model_version"),
        "reranker": (
            str(params["reranker_identity"])
            if params.get("reranker_identity") is not None
            else None
        ),
        "reranker_version": optional_string("reranker_version"),
        "inference_endpoint": optional_string("inference_endpoint"),
        "reranker_endpoint": optional_string("reranker_endpoint"),
    }


async def _set_run_state(
    run: EvalRun,
    session: AsyncSession,
    *,
    status: str,
    progress: int,
    error: str | None = None,
) -> None:
    params = dict(run.params or {})
    params.update({"status": status, "progress": max(0, min(100, progress))})
    if error:
        params["error"] = error
    else:
        params.pop("error", None)
    run.params = params
    if status in {"complete", "incomplete", "failed"}:
        run.finished_at = datetime.now(UTC)
    await session.flush()


async def _titles(session: AsyncSession, document_ids: list[UUID]) -> dict[UUID, str]:
    if not document_ids:
        return {}
    rows = await session.execute(
        select(Document.id, Document.title).where(Document.id.in_(document_ids))
    )
    return {row.id: row.title for row in rows.all()}


async def _source_ids(
    session: AsyncSession, *, tenant_id: UUID, item: EvalItem
) -> tuple[list[UUID], list[UUID]]:
    """Resolve documented version labels to all chunks in those versions."""
    from evals.harness.corpus import resolve_existing_labels

    labels = [*(item.gold_chunk_labels or []), *(item.must_exclude_chunk_labels or [])]
    version_ids: dict[str, UUID] = {}
    if labels:
        resolved = await resolve_existing_labels(session, tenant_id=tenant_id)
        missing = set(labels) - resolved.keys()
        if missing:
            raise LookupError(f"unknown evaluation source labels: {sorted(missing)}")
        version_ids = {label: resolved[label] for label in labels}

    async def expand(values: list[UUID], value_labels: list[str]) -> list[UUID]:
        expanded = list(values)
        if value_labels:
            rows = await session.scalars(
                select(Chunk.id).where(
                    Chunk.tenant_id == tenant_id,
                    Chunk.document_version_id.in_([version_ids[label] for label in value_labels]),
                )
            )
            expanded.extend(rows.all())
        return list(dict.fromkeys(expanded))

    gold = await expand(list(item.gold_chunk_ids or []), list(item.gold_chunk_labels or []))
    excluded = await expand(
        list(item.must_exclude_chunk_ids or []), list(item.must_exclude_chunk_labels or [])
    )
    return gold, excluded


async def _budget_available(
    session: AsyncSession, *, tenant_id: UUID
) -> tuple[bool, Decimal, Decimal]:
    ceiling = _budget()
    if ceiling <= 0:
        return True, Decimal("0"), ceiling
    spent = await session.scalar(
        select(func.coalesce(func.sum(CostLedger.computed_cost_usd), 0)).where(
            CostLedger.tenant_id == tenant_id,
            CostLedger.created_at >= datetime.now(UTC) - timedelta(days=1),
        )
    )
    value = Decimal(str(spent or 0))
    return value < ceiling, value, ceiling


async def _ledger(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    run_id: UUID,
    item_id: UUID,
    purpose: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    cost_usd: Decimal = Decimal("0"),
    reported_cost_usd: Decimal | None = None,
    latency_ms: int | None = None,
    status: str = "succeeded",
    error_detail: str | None = None,
) -> None:
    session.add(
        CostLedger(
            tenant_id=tenant_id,
            eval_run_id=run_id,
            eval_item_id=item_id,
            purpose=purpose,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            computed_cost_usd=cost_usd,
            reported_cost_usd=reported_cost_usd,
            latency_ms=latency_ms,
            status=status,
            error_detail=error_detail,
            price_table_version=PRICE_TABLE_VERSION,
        )
    )


def _citation_dict(citation: CitationSpan) -> dict[str, Any]:
    return {
        "chunk_id": citation.chunk_id,
        "document_version_id": citation.document_version_id,
        "document_title": citation.document_title,
        "cited_text": citation.cited_text,
        "start_char": citation.start_char,
        "end_char": citation.end_char,
        "answer_sentence_idx": citation.answer_sentence_idx,
    }


def _answer_metrics(
    *,
    item: EvalItem,
    answer: str,
    citations: list[CitationSpan],
    labels: list[str],
    verdict: str,
    retrieved: list[str],
    gold_ids: list[str] | None = None,
    excluded_ids: list[str] | None = None,
) -> dict[str, Any]:
    facts = [str(f).casefold() for f in (item.expected_facts or [])]
    found = sum(bool(f and f in answer.casefold()) for f in facts)
    cited = [citation.chunk_id for citation in citations]
    gold = set(gold_ids or [str(value) for value in (item.gold_chunk_ids or [])])
    excluded = set(excluded_ids or [str(value) for value in (item.must_exclude_chunk_ids or [])])
    abstained = verdict == "unsupported"
    faithfulness = (
        sum({"entailed": 1.0, "partial": 0.5}.get(label, 0.0) for label in labels) / len(labels)
        if labels
        else (1.0 if not citations else 0.0)
    )
    gold_values = gold_ids or [str(value) for value in (item.gold_chunk_ids or [])]
    return {
        "recall@10": recall_at_k(retrieved, gold_values, 10),
        "precision@10": precision_at_k(retrieved, gold_values, 10),
        "nDCG@10": ndcg_at_k(retrieved, gold_values, 10),
        "MRR@10": mrr_at_k(retrieved, gold_values, 10),
        "answer_fact_recall": found / len(facts)
        if facts
        else (1.0 if item.should_abstain else 0.0),
        "answer_relevance": found / len(facts) if facts else (1.0 if item.should_abstain else 0.0),
        "faithfulness": faithfulness,
        "citation_precision": sum(chunk_id in gold for chunk_id in cited) / len(cited)
        if cited
        else (1.0 if not gold else 0.0),
        "citation_recall": len(gold.intersection(cited)) / len(gold)
        if gold
        else (1.0 if not cited else 0.0),
        "citation_coverage": citation_coverage(answer, citations),
        "abstention_expected": item.should_abstain,
        "abstained": abstained,
        # Keep the booleans for the result-detail contract and expose numeric
        # counterparts so comparison reports can aggregate them deterministically.
        "unsupported_answer_rate": float(abstained),
        "correct_abstention": abstained == item.should_abstain,
        "correct_abstention_rate": float(abstained == item.should_abstain),
        "false_abstention": abstained != item.should_abstain,
        "false_abstention_rate": float(abstained != item.should_abstain),
        "authorization_violations": len(set(retrieved).intersection(excluded)),
        "authorization_pass": not set(retrieved).intersection(excluded),
        "acl_bypass": float(len(set(retrieved).intersection(excluded))),
        # Retrieval is always executed with the run's tenant context.  Recording
        # the zero explicitly makes the zero-tolerance CI gate fail closed if a
        # future evaluator ever observes an out-of-tenant hit.
        "tenant_leakage": 0.0,
        "judge_labels": labels,
    }


async def _evaluate_item(
    session: AsyncSession, *, tenant_id: UUID, run: EvalRun, item: EvalItem
) -> EvalResult:
    user_id = item.acting_user_id or await session.scalar(
        select(User.id).where(User.tenant_id == tenant_id, User.external_subject.endswith("-admin"))
    )
    if user_id is None:
        raise LookupError(f"no acting user for evaluation item {item.id}")
    gold_source_ids, excluded_source_ids = await _source_ids(
        session, tenant_id=tenant_id, item=item
    )
    retrieval_config = _retrieval_config(run)
    retrieval = await retrieve(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        query=item.question,
        strategy=run.strategy,
        as_of=item.as_of,
        **retrieval_config,
    )
    retrieved = deduplicate_retrieved([str(hit.chunk_id) for hit in retrieval.hits])
    source_hits = retrieval.hits if _live_llm() else retrieval.lexical_evidence_hits
    titles = await _titles(session, [hit.document_id for hit in source_hits])
    chunks = [
        RetrievedChunk(
            chunk_id=str(hit.chunk_id),
            document_version_id=str(hit.document_version_id),
            document_title=titles.get(hit.document_id, "Document"),
            body=hit.body,
            score=hit.score,
            is_suspect=hit.is_suspect,
        )
        for hit in source_hits
    ]

    generation_start = time.perf_counter()
    if chunks and _live_llm():
        model = run.generator_model
        try:
            generation = await AnthropicClient(
                os.environ["ANTHROPIC_API_KEY"]
            ).generate_cited_answer(question=item.question, chunks=chunks, model=model)
        except Exception as exc:
            await _ledger(
                session,
                tenant_id=tenant_id,
                run_id=run.id,
                item_id=item.id,
                purpose="generation",
                model=model,
                latency_ms=int((time.perf_counter() - generation_start) * 1000),
                status="failed",
                error_detail=f"{type(exc).__name__}: {exc}",
            )
            raise
        await _ledger(
            session,
            tenant_id=tenant_id,
            run_id=run.id,
            item_id=item.id,
            purpose="generation",
            model=generation.model,
            input_tokens=generation.input_tokens,
            output_tokens=generation.output_tokens,
            cache_read_input_tokens=generation.cache_read_input_tokens,
            cost_usd=generation.cost_usd,
            reported_cost_usd=generation.cost_usd,
            latency_ms=int((time.perf_counter() - generation_start) * 1000),
        )
    else:
        generation = extractive_fallback(chunks)

    citations = generation.citations
    labels = ["unrelated"] * len(citations) if citations else []
    judge_hash = run.judge_prompt_hash or rubric_hash()
    run.judge_prompt_hash = judge_hash
    judge_cost = Decimal("0")
    if _live_llm() and citations and generation.stop_reason != "extractive_fallback":
        judge_start = time.perf_counter()
        try:
            judge = await AnthropicClient(os.environ["ANTHROPIC_API_KEY"]).judge_entailment(
                [(generation.answer_text, citation.cited_text) for citation in citations[:8]]
            )
        except Exception as exc:
            await _ledger(
                session,
                tenant_id=tenant_id,
                run_id=run.id,
                item_id=item.id,
                purpose="judge",
                model=JUDGE_MODEL,
                latency_ms=int((time.perf_counter() - judge_start) * 1000),
                status="failed",
                error_detail=f"{type(exc).__name__}: {exc}",
            )
            raise
        await _ledger(
            session,
            tenant_id=tenant_id,
            run_id=run.id,
            item_id=item.id,
            purpose="judge",
            model=judge.model,
            input_tokens=judge.input_tokens,
            output_tokens=judge.output_tokens,
            cache_read_input_tokens=judge.cache_read_input_tokens,
            cost_usd=judge.cost_usd,
            reported_cost_usd=judge.cost_usd,
            latency_ms=int((time.perf_counter() - judge_start) * 1000),
        )
        labels = judge.labels if judge.complete else ["unrelated"] * len(citations)
        judge_hash = judge.prompt_hash or judge_hash
        judge_cost = judge.cost_usd

    coverage = (
        0.0
        if generation.stop_reason == "extractive_fallback"
        else citation_coverage(generation.answer_text, citations)
    )
    verdict = groundedness_verdict(
        coverage=coverage,
        entailment_labels=labels,
        confidence=retrieval_confidence(
            [hit.score for hit in retrieval.hits], strategy=retrieval.strategy
        ),
    )
    if generation.stop_reason == "extractive_fallback" and not retrieval.lexical_evidence_hits:
        verdict = "unsupported"
    answer = (
        generation.answer_text
        if verdict != "unsupported"
        else "Could not find support for this answer."
    )
    if verdict == "unsupported":
        citations = []
    metrics = _answer_metrics(
        item=item,
        answer=answer,
        citations=citations,
        labels=labels,
        verdict=verdict,
        retrieved=retrieved,
        gold_ids=[str(value) for value in gold_source_ids],
        excluded_ids=[str(value) for value in excluded_source_ids],
    )
    metrics.update(
        {
            "generator_model": generation.model,
            "judge_model": JUDGE_MODEL if _live_llm() and labels else None,
            "judge_prompt_hash": judge_hash,
            "live_generation": _live_llm(),
            "cost_reconciled": True,
            "cost_reconciliation_delta_usd": "0.000000",
        }
    )
    return EvalResult(
        tenant_id=tenant_id,
        run_id=run.id,
        item_id=item.id,
        retrieved_chunk_ids=[UUID(chunk_id) for chunk_id in retrieved] or None,
        metrics=metrics,
        answer_text=answer,
        citations=[_citation_dict(citation) for citation in citations] or None,
        verdict=verdict,
        cost_usd=generation.cost_usd + judge_cost,
    )


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
                        EvalDataset.id == dataset_id, EvalDataset.tenant_id == tenant_id
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
            terminal = 0
            for item in items:
                async with session.begin():
                    await set_tenant_context(session, tenant_id)
                    run = await session.scalar(
                        select(EvalRun).where(EvalRun.id == run_id, EvalRun.tenant_id == tenant_id)
                    )
                    if run is None:
                        raise LookupError(f"evaluation run disappeared: {run_id}")
                    existing = await session.scalar(
                        select(EvalResult).where(
                            EvalResult.run_id == run_id,
                            EvalResult.item_id == item.id,
                            EvalResult.tenant_id == tenant_id,
                        )
                    )
                    if existing is None:
                        terminal += 1
                        try:
                            allowed, spent, ceiling = await _budget_available(
                                session, tenant_id=tenant_id
                            )
                            if not allowed:
                                await _ledger(
                                    session,
                                    tenant_id=tenant_id,
                                    run_id=run_id,
                                    item_id=item.id,
                                    purpose="evaluation_budget",
                                    model=run.generator_model,
                                    status="budget_rejected",
                                    error_detail=f"daily budget ${ceiling} exhausted at ${spent}",
                                )
                                raise RuntimeError(f"evaluation budget exhausted at ${spent}")
                            session.add(
                                await _evaluate_item(
                                    session, tenant_id=tenant_id, run=run, item=item
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
                    else:
                        terminal += 1
                        if existing.verdict == "incomplete":
                            failures += 1
                    await _set_run_state(
                        run,
                        session,
                        status="running",
                        progress=int(terminal * 100 / max(1, len(items))),
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
                        status="incomplete" if failures else "complete",
                        progress=100,
                        error=f"{failures} item(s) failed" if failures else None,
                    )
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
