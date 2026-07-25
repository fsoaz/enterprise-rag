"""Unit tests for Reciprocal Rank Fusion (no DB)."""

from __future__ import annotations

from uuid import uuid4

from retrieval.fusion import reciprocal_rank_fusion


def test_rrf_prefers_items_ranked_high_in_both_lists() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    fused = reciprocal_rank_fusion([[a, b, c], [a, c, b]], k=60)
    assert fused[0][0] == a
    scores = dict(fused)
    assert scores[a] > scores[b]
    assert scores[a] > scores[c]


def test_rrf_k_affects_score() -> None:
    x = uuid4()
    low_k = reciprocal_rank_fusion([[x]], k=1)[0][1]
    high_k = reciprocal_rank_fusion([[x]], k=60)[0][1]
    assert low_k > high_k


def test_rrf_empty() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []
