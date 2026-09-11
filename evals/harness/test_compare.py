from __future__ import annotations

from uuid import uuid4

import pytest

from evals.harness.compare import (
    ComparisonConfigError,
    expand_sweep,
    run_comparison,
    validate_config,
)
from evaluation.report import ComparisonError


def test_default_sweep_is_cartesian_and_baseline_first() -> None:
    config = validate_config({"dataset_id": str(uuid4())})
    specs = expand_sweep(config)
    assert len(specs) == 4
    assert [spec.strategy for spec in specs] == [
        "hybrid_rrf",
        "dense_only",
        "lexical_only",
        "hybrid_rerank",
    ]


def test_configuration_is_strict_and_duplicate_combinations_are_rejected() -> None:
    with pytest.raises(ComparisonConfigError, match="unknown fields"):
        validate_config({"dataset_id": str(uuid4()), "unexpected": True})
    with pytest.raises(ComparisonConfigError, match="duplicate sweep"):
        expand_sweep(
            validate_config(
                {
                    "dataset_id": str(uuid4()),
                    "embedding_models": [
                        {"name": "embed", "version": "v1"},
                        {"name": "embed", "version": "v1"},
                    ],
                }
            )
        )


def test_configuration__chunking_strategy__is_validated_and_preserved() -> None:
    config = validate_config({"dataset_id": str(uuid4()), "chunking_strategy": "section_aware"})
    assert config.chunking_strategy == "section_aware"
    with pytest.raises(ComparisonConfigError, match="unsupported chunking_strategy"):
        validate_config({"dataset_id": str(uuid4()), "chunking_strategy": "random"})


def test_runner_uses_sequential_run_worker_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = str(uuid4())
    config = validate_config(
        {
            "dataset_id": dataset_id,
            "poll_interval_seconds": 0.001,
            "bootstrap_resamples": 100,
        }
    )
    calls: list[tuple[str, str]] = []
    created: list[str] = []

    def fake_request(url: str, *, method: str = "GET", body: object = None, user: str) -> object:
        del user
        calls.append((method, url))
        if method == "POST":
            run_id = str(uuid4())
            created.append(run_id)
            assert isinstance(body, dict)
            assert body["params"]["comparison"]["dataset_id"] == dataset_id
            return {"id": run_id}
        if "/results" in url:
            run_id = url.split("/runs/")[1].split("/")[0]
            return {"data": [{"item_id": "item-1", "metrics": {"recall@10": 1.0}}]}
        if "/items" in url:
            return {"data": [{"id": "item-1", "slice": "default"}]}
        run_id = url.rsplit("/", 1)[-1]
        return {
            "id": run_id,
            "dataset_id": dataset_id,
            "strategy": "hybrid_rrf",
            "embedding_model": "embed",
            "reranker": None,
            "generator_model": "extractive-fallback",
            "status": "complete",
            "params": {"status": "complete"},
        }

    monkeypatch.setattr("evals.harness.compare._http_json", fake_request)
    report = run_comparison(config)
    assert report["baseline_run_id"] == created[0]
    assert len(created) == 4
    assert [method for method, _ in calls].count("POST") == 4
    assert [method for method, _ in calls].index("POST") < [method for method, _ in calls].index(
        "GET"
    )


def test_runner__run_not_found__fails_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    config = validate_config({"dataset_id": str(uuid4())})
    lookups = []

    def fake_request(url: str, *, method: str = "GET", body: object = None, user: str) -> object:
        if method == "POST":
            return {"id": "missing"}
        lookups.append(url)
        raise ComparisonError("comparison API request failed: HTTP Error 404")

    def unexpected_sleep(seconds: float) -> None:
        pytest.fail("404 must fail immediately without sleeping")

    monkeypatch.setattr("evals.harness.compare._http_json", fake_request)
    monkeypatch.setattr("evals.harness.compare.time.sleep", unexpected_sleep)
    with pytest.raises(ComparisonError, match="HTTP Error 404"):
        run_comparison(config)
    assert len(lookups) == 1


def test_runner__queued_run__polls_until_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    config = validate_config({"dataset_id": str(uuid4()), "timeout_seconds": 1})
    clock = iter([0.0, 0.5, 1.0])
    sleeps = []

    def fake_request(url: str, *, method: str = "GET", body: object = None, user: str) -> object:
        return {"id": "queued", "status": "queued"}

    monkeypatch.setattr("evals.harness.compare._http_json", fake_request)
    monkeypatch.setattr("evals.harness.compare.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("evals.harness.compare.time.sleep", sleeps.append)
    with pytest.raises(ComparisonError, match="before timeout"):
        run_comparison(config)
    assert sleeps == [config.poll_interval_seconds]
