"""Reciprocal Rank Fusion (architecture § 7.6)."""

from __future__ import annotations

from uuid import UUID

from domain.types import DEFAULT_RRF_K


def reciprocal_rank_fusion(
    ranked_lists: list[list[UUID]],
    *,
    k: int = DEFAULT_RRF_K,
) -> list[tuple[UUID, float]]:
    """Merge ranked ID lists with score(d) = Σ 1/(k + rank). Ranks are 1-based."""
    scores: dict[UUID, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)
