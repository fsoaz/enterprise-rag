from __future__ import annotations

from copy import deepcopy

import pytest

from evals.harness.gate import GateError, RegressionDetected, evaluate_gate


def _envelope(*, value: float = 0.8, item_count: int = 2) -> dict[str, object]:
    run_ids = {"hybrid_rrf": "baseline", "dense_only": "candidate"}
    metrics = {
        "recall@10": value,
        "nDCG@10": value,
        "faithfulness": value,
        "citation_precision": value,
        "unsupported_answer_rate": 0.1,
        "correct_abstention_rate": value,
        "tenant_leakage": 0.0,
        "acl_bypass": 0.0,
    }
    return {
        "schema_version": 1,
        "metadata": {
            "dataset": {
                "name": "t407",
                "version": "smoke-v1",
                "content_sha256": "digest",
                "item_count": item_count,
                "item_ids": ["a", "b"][:item_count],
            },
            "config": {
                "strategies": ["hybrid_rrf", "dense_only"],
                "baseline": "hybrid_rrf",
                "embedding_models": [{"name": "embed", "version": "stub-v0"}],
                "rerankers": [{"name": "identity", "version": "stub-v0"}],
                "retrieval_params": [{}],
            },
        },
        "report": {
            "runs": [{"id": run_id, "strategy": strategy} for strategy, run_id in run_ids.items()],
            "overall": {
                metric: {
                    run_id: {"value": metric_value}
                    for run_id, metric_value in (
                        ("baseline", metric_value),
                        ("candidate", metric_value),
                    )
                }
                for metric, metric_value in metrics.items()
            },
        },
    }


def test_gate_accepts_a_compatible_known_good_report() -> None:
    baseline = _envelope()
    current = deepcopy(baseline)
    result = evaluate_gate(current, baseline)
    assert result.passed is True
    assert "recall@10" in result.checked_metrics


def test_gate_rejects_missing_required_metrics() -> None:
    baseline = _envelope()
    current = deepcopy(baseline)
    del current["report"]["overall"]["recall@10"]  # type: ignore[index]
    with pytest.raises(GateError, match="recall@10"):
        evaluate_gate(current, baseline)


def test_gate_rejects_incompatible_baselines() -> None:
    baseline = _envelope()
    current = _envelope(item_count=1)
    with pytest.raises(GateError, match="item_count"):
        evaluate_gate(current, baseline)


def test_gate_detects_a_deliberate_quality_regression() -> None:
    baseline = _envelope(value=0.9)
    current = _envelope(value=0.87)
    with pytest.raises(RegressionDetected, match="recall@10"):
        evaluate_gate(current, baseline)


@pytest.mark.parametrize("metric", ["tenant_leakage", "acl_bypass"])
@pytest.mark.parametrize("run_id", ["baseline", "candidate"])
def test_gate__security_violation_in_any_run__fails(metric: str, run_id: str) -> None:
    baseline = _envelope()
    current = _envelope()
    current["report"]["overall"][metric][run_id]["value"] = 0.00001  # type: ignore[index]
    with pytest.raises(RegressionDetected, match=metric):
        evaluate_gate(current, baseline)
    with pytest.raises(GateError, match="committed baseline has non-zero"):
        evaluate_gate(baseline, current)


@pytest.mark.parametrize("metric", ["recall@10", "nDCG@10"])
@pytest.mark.parametrize("drop,passes", [(0.019, True), (0.021, False)])
def test_gate__retrieval_allowance__enforced(metric: str, drop: float, passes: bool) -> None:
    baseline = _envelope()
    current = _envelope()
    current["report"]["overall"][metric]["baseline"]["value"] = 0.8 - drop  # type: ignore[index]
    if passes:
        assert evaluate_gate(current, baseline).passed
    else:
        with pytest.raises(RegressionDetected, match=metric):
            evaluate_gate(current, baseline)


def test_gate__answer_metrics_regress__remain_report_only() -> None:
    baseline = _envelope()
    current = _envelope()
    values = {
        "faithfulness": 0.0,
        "citation_precision": 0.0,
        "unsupported_answer_rate": 1.0,
        "correct_abstention_rate": 0.0,
    }
    for metric, value in values.items():
        for run_id in ("baseline", "candidate"):
            current["report"]["overall"][metric][run_id]["value"] = value  # type: ignore[index]
    report = deepcopy(current)
    result = evaluate_gate(current, baseline)
    assert result.passed
    assert set(result.checked_metrics) == {
        "recall@10",
        "nDCG@10",
        "tenant_leakage:baseline",
        "tenant_leakage:candidate",
        "acl_bypass:baseline",
        "acl_bypass:candidate",
    }
    assert current == report
