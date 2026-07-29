from __future__ import annotations

import re
from typing import Literal

from domain.types import DEFAULT_RRF_K, RetrievalStrategy
from llm.client import CitationSpan, Groundedness, split_sentences

DISCOURSE = re.compile(
    r"^(here('s| is)|below|the following|in summary|resumo|segue)\b",
    re.IGNORECASE,
)

__all__ = [
    "citation_coverage",
    "groundedness_verdict",
    "normalize_scores",
    "retrieval_confidence",
    "should_abstain",
    "split_sentences",
]

# ts_rank_cd is unbounded above but clusters low; this is the value that maps to a
# normalized 0.5 under the saturating transform below. Chosen so an ordinary FTS
# match lands mid-scale rather than pinned at either end.
LEXICAL_HALF_SATURATION = 0.1


def citation_coverage(answer: str, citations: list[CitationSpan]) -> float:
    """Fraction of substantive answer sentences carrying at least one citation.

    ``answer_sentence_idx`` indexes the *full* sentence list, so discourse
    sentences are excluded by index rather than by rebuilding a filtered list —
    filtering first renumbered the survivors and made every citation index refer
    to the wrong sentence.
    """
    sentences = split_sentences(answer)
    if not sentences:
        return 1.0
    # Framing sentences ("In summary, ...") assert nothing and need no source.
    substantive = [i for i, s in enumerate(sentences) if not DISCOURSE.match(s)]
    if not substantive:
        return 1.0
    cited_idxs = {c.answer_sentence_idx for c in citations}
    covered = sum(1 for i in substantive if i in cited_idxs)
    return covered / len(substantive)


def normalize_scores(
    scores: list[float],
    *,
    strategy: RetrievalStrategy | str = RetrievalStrategy.HYBRID_RRF,
    rrf_k: int = DEFAULT_RRF_K,
    fused_lists: int = 2,
) -> list[float]:
    """Map raw retrieval scores onto a common 0..1 scale.

    Each strategy returns a different quantity, and they are not comparable:

    ==================  ======================  ==========================
    strategy            raw score               theoretical maximum
    ==================  ======================  ==========================
    ``dense_only``      cosine similarity       1.0
    ``hybrid_rerank``   cross-encoder score     1.0
    ``hybrid_rrf``      Σ 1/(k + rank)          ``fused_lists / (k + 1)``
    ``lexical_only``    ``ts_rank_cd``          unbounded, clusters low
    ==================  ======================  ==========================

    Feeding these to a single absolute threshold is what made the default
    strategy unusable: with k=60 and two arms, an RRF score cannot exceed
    2/61 ≈ 0.033, so *every* hybrid_rrf query fell under a 0.05 floor and the
    system abstained regardless of how good the retrieval actually was.
    """
    value = strategy.value if isinstance(strategy, RetrievalStrategy) else str(strategy)
    if not scores:
        return []

    if value == RetrievalStrategy.HYBRID_RRF.value:
        ceiling = fused_lists / (rrf_k + 1)
        return [min(1.0, max(0.0, s / ceiling)) for s in scores]

    if value == RetrievalStrategy.LEXICAL_ONLY.value:
        # Saturating: monotonic, bounded, and never zero for a real match.
        return [max(0.0, s) / (max(0.0, s) + LEXICAL_HALF_SATURATION) for s in scores]

    # dense_only / hybrid_rerank already produce a 0..1 similarity.
    return [min(1.0, max(0.0, s)) for s in scores]


def retrieval_confidence(
    scores: list[float],
    *,
    strategy: RetrievalStrategy | str = RetrievalStrategy.HYBRID_RRF,
    rrf_k: int = DEFAULT_RRF_K,
    fused_lists: int = 2,
) -> float:
    """Confidence in 0..1: how strong the top hit is, and how far it leads the pack.

    Normalizes first so the result is comparable across strategies and can be
    tested against a single floor.
    """
    normalized = normalize_scores(scores, strategy=strategy, rrf_k=rrf_k, fused_lists=fused_lists)
    if not normalized:
        return 0.0
    top = normalized[0]
    gap = top - normalized[min(4, len(normalized) - 1)] if len(normalized) > 1 else top
    return max(0.0, min(1.0, top * 0.7 + gap * 0.3))


def groundedness_verdict(
    *,
    coverage: float,
    entailment_labels: list[str],
    confidence: float,
    coverage_floor: float = 0.6,
    # ``confidence`` is now normalized to 0..1 by retrieval_confidence, so this
    # floor is comparable across strategies. The old 0.05 was set against raw
    # mixed-scale scores and was unreachable under hybrid_rrf. Re-tune against the
    # eval golden set before moving it further.
    confidence_floor: float = 0.15,
) -> Groundedness:
    if any(label == "contradicted" for label in entailment_labels):
        return "unsupported"
    # Unmatched judge pairs default to ``unrelated`` — treat an entirely
    # unmatched set as unsupported rather than silently grounding.
    if entailment_labels and all(label == "unrelated" for label in entailment_labels):
        return "unsupported"
    if coverage < coverage_floor or confidence < confidence_floor:
        return "unsupported"
    if coverage < 0.9 or any(label == "partial" for label in entailment_labels):
        return "partial"
    return "grounded"


def should_abstain(verdict: Literal["grounded", "partial", "unsupported"]) -> bool:
    return verdict == "unsupported"
