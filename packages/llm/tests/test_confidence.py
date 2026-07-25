"""Regression tests for the retrieval-confidence scale.

The default strategy used to be structurally incapable of producing a grounded
verdict: RRF scores are bounded by ``fused_lists / (k + 1)`` = 2/61 ≈ 0.033, and
the confidence floor was 0.05, so every hybrid_rrf query abstained no matter how
good the retrieval was.
"""

from __future__ import annotations

from domain.types import DEFAULT_RRF_K
from llm.client import CitationSpan, sentence_index_for_offset, sentence_start_offsets
from llm.groundedness import (
    citation_coverage,
    groundedness_verdict,
    normalize_scores,
    retrieval_confidence,
)


def _rrf_best(fused_lists: int = 2, k: int = DEFAULT_RRF_K) -> float:
    """Score of a chunk ranked first in every arm — the theoretical RRF maximum."""
    return fused_lists * (1.0 / (k + 1))


def test_perfect_rrf_retrieval_can_reach_grounded() -> None:
    confidence = retrieval_confidence([_rrf_best(), 0.005, 0.004], strategy="hybrid_rrf")
    assert confidence > 0.5
    assert (
        groundedness_verdict(coverage=1.0, entailment_labels=["entailed"], confidence=confidence)
        == "grounded"
    )


def test_rrf_normalization_maps_theoretical_max_to_one() -> None:
    assert normalize_scores([_rrf_best()], strategy="hybrid_rrf")[0] == 1.0


def test_strategies_are_comparable_after_normalization() -> None:
    """A top hit in each strategy should land in the same neighbourhood."""
    rrf = retrieval_confidence([_rrf_best()], strategy="hybrid_rrf")
    dense = retrieval_confidence([1.0], strategy="dense_only")
    rerank = retrieval_confidence([1.0], strategy="hybrid_rerank")
    assert abs(rrf - dense) < 0.01
    assert abs(dense - rerank) < 0.01


def test_weak_retrieval_still_abstains() -> None:
    """Normalization must not turn the floor into a rubber stamp."""
    confidence = retrieval_confidence([0.0005, 0.0005, 0.0005], strategy="hybrid_rrf")
    assert (
        groundedness_verdict(coverage=1.0, entailment_labels=["entailed"], confidence=confidence)
        == "unsupported"
    )


def test_empty_retrieval_has_zero_confidence() -> None:
    assert retrieval_confidence([], strategy="hybrid_rrf") == 0.0


def test_lexical_scores_are_bounded() -> None:
    assert all(0.0 <= s <= 1.0 for s in normalize_scores([0.0, 0.05, 5.0], strategy="lexical_only"))


def _span(sentence_idx: int) -> CitationSpan:
    return CitationSpan("chunk", "version", "Doc", "text", 0, 4, sentence_idx)


def test_sentence_offsets_map_to_the_containing_sentence() -> None:
    answer = "Passwords rotate every 90 days. Secrets live in the vault. Nothing else."
    starts = sentence_start_offsets(answer)
    assert sentence_index_for_offset(starts, 0) == 0
    assert sentence_index_for_offset(starts, 40) == 1
    assert sentence_index_for_offset(starts, 60) == 2


def test_coverage_counts_by_sentence_index() -> None:
    answer = "One claim. Two claim. Three claim."
    assert citation_coverage(answer, [_span(0), _span(1), _span(2)]) == 1.0
    assert abs(citation_coverage(answer, [_span(0)]) - 1 / 3) < 1e-9


def test_discourse_sentences_do_not_shift_citation_indices() -> None:
    """Filtering framing sentences out of the list renumbered the survivors."""
    answer = "In summary, the policy is clear. Passwords rotate every 90 days."
    # Sentence 1 is the only substantive claim, and it is cited.
    assert citation_coverage(answer, [_span(1)]) == 1.0
    # Citing only the framing sentence leaves the real claim unsupported.
    assert citation_coverage(answer, [_span(0)]) == 0.0
