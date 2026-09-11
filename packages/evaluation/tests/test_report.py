from __future__ import annotations

from uuid import uuid4

import pytest

from evaluation.report import ComparisonError, build_report, paired_bootstrap_ci


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
