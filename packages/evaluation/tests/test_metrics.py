from __future__ import annotations

from evaluation.metrics import (
    aggregate_grouped_metrics,
    aggregate_retrieval_metrics,
    deduplicate_retrieved,
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_recall() -> None:
    assert recall_at_k(["a", "b"], ["b"], 5) == 1.0
    assert recall_at_k(["a", "b"], ["z"], 10) == 0.0


def test_mrr_and_ndcg() -> None:
    assert mrr_at_k(["x", "gold"], ["gold"], 10) == 0.5
    assert ndcg_at_k(["gold"], ["gold"], 10) == 1.0


def test_aggregate() -> None:
    metrics = aggregate_retrieval_metrics([(["g"], ["g"]), (["x"], ["g"])])
    assert metrics["recall@10"] == 0.5


def test_duplicate_versions_are_collapsed_before_scoring() -> None:
    retrieved = deduplicate_retrieved(["v1", "v1", "v2"])
    assert retrieved == ["v1", "v2"]
    assert precision_at_k(retrieved, ["v2"], 10) == 0.5


def test_empty_gold_is_only_perfect_when_nothing_was_retrieved() -> None:
    assert recall_at_k([], [], 10) == 1.0
    assert recall_at_k(["distractor"], [], 10) == 0.0


def test_metrics_are_grouped_by_slice_and_language() -> None:
    report = aggregate_grouped_metrics(
        [
            ("factual_en", "en", ["gold"], ["gold"]),
            ("factual_pt", "pt", ["miss"], ["gold"]),
        ]
    )
    assert set(report) == {"factual_en:en", "factual_pt:pt"}
    assert report["factual_en:en"]["recall@10"] == 1.0
