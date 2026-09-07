from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from db.models import EvalItem, EvalRun
from llm.client import CitationSpan, GenerationResult, JudgeResult
from worker.celery_app import celery_app
from worker.tasks import eval as eval_task
from worker.tasks.eval import _answer_metrics, _evaluate_item, _retrieval_config


def test_evaluation_worker_task_is_registered() -> None:
    task = celery_app.tasks["worker.tasks.eval.run_eval"]
    assert task.max_retries == 3
    assert task.retry_backoff is True
    assert task.autoretry_for == (Exception,)


def test_answer_metrics_record_quality_abstention_and_authorization() -> None:
    item = EvalItem(
        id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        question="What is unavailable?",
        expected_facts=["three working days"],
        should_abstain=True,
    )
    metrics = _answer_metrics(
        item=item,
        answer="Could not find support for this answer.",
        citations=[],
        labels=[],
        verdict="unsupported",
        retrieved=[],
    )
    assert metrics["abstained"] is True
    assert metrics["correct_abstention"] is True
    assert metrics["citation_precision"] == 1.0
    assert metrics["authorization_pass"] is True


def test_retrieval_config_treats_json_null_endpoints_as_unset() -> None:
    run = EvalRun(
        params={
            "embedding_model_name": "BAAI/bge-m3",
            "embedding_model_version": "stub-v0",
            "inference_endpoint": None,
            "reranker_identity": None,
            "reranker_version": None,
            "reranker_endpoint": None,
        }
    )
    config = _retrieval_config(run)
    assert config["inference_endpoint"] is None
    assert config["reranker_endpoint"] is None
    assert config["reranker"] is None


@pytest.mark.asyncio
async def test_generation_failure_is_represented_in_the_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        def __init__(self) -> None:
            self.rows: list[object] = []

        def add(self, row: object) -> None:
            self.rows.append(row)

        async def scalar(self, statement: object) -> object:
            return uuid4()

    class FailingClient:
        def __init__(self, api_key: str) -> None:
            del api_key

        async def generate_cited_answer(self, **kwargs: object) -> object:
            del kwargs
            raise RuntimeError("model unavailable")

    hit = SimpleNamespace(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        body="A source passage.",
        score=0.9,
        is_suspect=False,
    )
    retrieval_result = SimpleNamespace(
        hits=[hit], lexical_evidence_hits=[hit], strategy="lexical_only"
    )
    session = Session()
    run = EvalRun(
        id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        strategy="lexical_only",
        embedding_model="stub-v0",
        generator_model="claude-opus-5",
        started_at=datetime.now(UTC),
    )
    item = EvalItem(
        id=uuid4(),
        tenant_id=run.tenant_id,
        dataset_id=run.dataset_id,
        question="What is the policy?",
        acting_user_id=uuid4(),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(eval_task, "AnthropicClient", FailingClient)

    async def fake_retrieve(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return retrieval_result

    async def fake_titles(*args: object, **kwargs: object) -> dict[object, str]:
        del args, kwargs
        return {}

    monkeypatch.setattr(eval_task, "retrieve", fake_retrieve)
    monkeypatch.setattr(eval_task, "_titles", fake_titles)

    with pytest.raises(RuntimeError, match="model unavailable"):
        await _evaluate_item(cast(Any, session), tenant_id=run.tenant_id, run=run, item=item)
    ledger = [row for row in session.rows if row.__class__.__name__ == "CostLedger"]
    assert len(ledger) == 1
    ledger_row = cast(Any, ledger[0])
    assert ledger_row.purpose == "generation"
    assert ledger_row.status == "failed"


@pytest.mark.asyncio
async def test_success_records_generation_and_versioned_judge_costs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        def __init__(self) -> None:
            self.rows: list[object] = []

        def add(self, row: object) -> None:
            self.rows.append(row)

    class SuccessfulClient:
        def __init__(self, api_key: str) -> None:
            del api_key

        async def generate_cited_answer(self, **kwargs: object) -> GenerationResult:
            del kwargs
            return GenerationResult(
                answer_text="The policy requires three working days.",
                citations=[citation],
                model="claude-opus-5",
                input_tokens=10,
                output_tokens=5,
                cache_read_input_tokens=0,
                stop_reason="end_turn",
                cost_usd=Decimal("0.000100"),
            )

        async def judge_entailment(self, pairs: list[tuple[str, str]]) -> JudgeResult:
            assert pairs
            return JudgeResult(
                labels=["entailed"],
                model="claude-haiku-4-5",
                input_tokens=4,
                output_tokens=2,
                cost_usd=Decimal("0.000010"),
                prompt_hash="judge-hash",
            )

    citation = CitationSpan(
        chunk_id=str(uuid4()),
        document_version_id=str(uuid4()),
        document_title="Policy",
        cited_text="three working days",
        start_char=0,
        end_char=19,
        answer_sentence_idx=0,
    )
    hit = SimpleNamespace(
        chunk_id=UUID(citation.chunk_id),
        document_id=uuid4(),
        document_version_id=UUID(citation.document_version_id),
        body="three working days",
        score=0.9,
        is_suspect=False,
    )
    retrieval_result = SimpleNamespace(
        hits=[hit], lexical_evidence_hits=[hit], strategy="lexical_only"
    )
    session = Session()
    run = EvalRun(
        id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        strategy="lexical_only",
        embedding_model="stub-v0",
        generator_model="claude-opus-5",
        started_at=datetime.now(UTC),
    )
    item = EvalItem(
        id=uuid4(),
        tenant_id=run.tenant_id,
        dataset_id=run.dataset_id,
        question="What is the policy?",
        expected_facts=["three working days"],
        gold_chunk_ids=[UUID(citation.chunk_id)],
        acting_user_id=uuid4(),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(eval_task, "AnthropicClient", SuccessfulClient)

    async def fake_retrieve(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return retrieval_result

    async def fake_titles(*args: object, **kwargs: object) -> dict[object, str]:
        del args, kwargs
        return {}

    monkeypatch.setattr(eval_task, "retrieve", fake_retrieve)
    monkeypatch.setattr(eval_task, "_titles", fake_titles)
    result = await _evaluate_item(cast(Any, session), tenant_id=run.tenant_id, run=run, item=item)

    ledgers = [row for row in session.rows if row.__class__.__name__ == "CostLedger"]
    assert [cast(Any, row).purpose for row in ledgers] == ["generation", "judge"]
    assert result.verdict == "grounded"
    assert result.citations is not None
    assert result.cost_usd == Decimal("0.000110")
