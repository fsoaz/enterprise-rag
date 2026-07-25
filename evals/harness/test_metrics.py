from __future__ import annotations

from evals.harness.metrics import aggregate_retrieval_metrics, recall_at_k


def test_recall() -> None:
    assert recall_at_k(["a", "b"], ["b"], 5) == 1.0


def test_aggregate() -> None:
    metrics = aggregate_retrieval_metrics([(["g"], ["g"]), (["x"], ["g"])])
    assert metrics["recall@10"] == 0.5
