from __future__ import annotations

from uuid import uuid4

import pytest

from evals.harness.compare import (
    ComparisonConfigError,
    ComparisonError,
    build_report,
    expand_sweep,
    paired_bootstrap_ci,
    run_comparison,
    validate_config,
)


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


def test_report_aligns_items_and_is_deterministically_significant() -> None:
    baseline = str(uuid4())
    candidate = str(uuid4())
    runs = [
        {
            "id": baseline,
            "dataset_id": "dataset",
            "strategy": "hybrid_rrf",
            "params": {"status": "complete"},
        },
        {
            "id": candidate,
            "dataset_id": "dataset",
            "strategy": "dense_only",
            "params": {"status": "complete"},
        },
    ]
    items = [
        {"id": "item-a", "slice": "factual_en"},
        {"id": "item-b", "slice": "factual_en"},
        {"id": "item-c", "slice": "permission"},
    ]
    results = {
        baseline: [{"item_id": item["id"], "metrics": {"recall@10": 0.0}} for item in items],
        candidate: [{"item_id": item["id"], "metrics": {"recall@10": 1.0}} for item in items],
    }
    report = build_report(runs, items, results, bootstrap_resamples=1000)
    metric = report["by_slice"]["factual_en"]["recall@10"][candidate]
    assert report["baseline_run_id"] == baseline
    assert metric["delta"] == 1.0
    assert metric["confidence_interval"]["lower"] == 1.0
    assert metric["significant"] is True
    assert report["coverage"]["overall"][candidate]["result_count"] == 3


def test_report_rejects_incomplete_and_missing_results() -> None:
    run_id = str(uuid4())
    run = {"id": run_id, "dataset_id": "dataset", "params": {"status": "running"}}
    item = {"id": "item-a", "slice": "default"}
    with pytest.raises(ComparisonError, match="incomplete"):
        build_report([run, {**run, "id": str(uuid4())}], [item], {run_id: []})
    complete = {**run, "params": {"status": "complete"}}
    with pytest.raises(ComparisonError, match="missing or duplicate results"):
        build_report([complete, {**complete, "id": str(uuid4())}], [item], {run_id: []})


def test_bootstrap_is_deterministic_and_empty_observations_are_null() -> None:
    first = paired_bootstrap_ci([0.1, 0.2, 0.3], resamples=1000, seed=7)
    assert first == paired_bootstrap_ci([0.1, 0.2, 0.3], resamples=1000, seed=7)
    assert paired_bootstrap_ci([], resamples=1000) is None


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
