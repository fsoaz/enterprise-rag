from __future__ import annotations

import re
from typing import Literal

from llm.client import CitationSpan, Groundedness

DISCOURSE = re.compile(
    r"^(here('s| is)|below|the following|in summary|resumo|segue)\b",
    re.IGNORECASE,
)


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def citation_coverage(answer: str, citations: list[CitationSpan]) -> float:
    sentences = [s for s in split_sentences(answer) if not DISCOURSE.match(s)]
    if not sentences:
        return 1.0
    cited_idxs = {c.answer_sentence_idx for c in citations}
    # Map by index when available; also count if any citation exists for short answers
    covered = 0
    for i, _sentence in enumerate(sentences):
        if i in cited_idxs:
            covered += 1
    if covered == 0 and citations:
        # Native citations may not align 1:1 with sentence splits — treat as partial credit
        return min(1.0, len(citations) / max(len(sentences), 1))
    return covered / len(sentences)


def retrieval_confidence(scores: list[float]) -> float:
    if not scores:
        return 0.0
    top = scores[0]
    gap = top - scores[min(4, len(scores) - 1)] if len(scores) > 1 else top
    return float(top) * 0.7 + float(gap) * 0.3


def groundedness_verdict(
    *,
    coverage: float,
    entailment_labels: list[str],
    confidence: float,
    coverage_floor: float = 0.6,
    confidence_floor: float = 0.05,
) -> Groundedness:
    if any(label == "contradicted" for label in entailment_labels):
        return "unsupported"
    if coverage < coverage_floor or confidence < confidence_floor:
        return "unsupported"
    if coverage < 0.9 or any(label == "partial" for label in entailment_labels):
        return "partial"
    return "grounded"


def should_abstain(verdict: Literal["grounded", "partial", "unsupported"]) -> bool:
    return verdict == "unsupported"
