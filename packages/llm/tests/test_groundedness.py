from __future__ import annotations

from evals.harness.metrics import mrr_at_k, ndcg_at_k, recall_at_k

from llm.client import CitationSpan
from llm.groundedness import citation_coverage, groundedness_verdict


def test_recall_at_k() -> None:
    assert recall_at_k(["a", "b", "c"], ["c"], 10) == 1.0
    assert recall_at_k(["a", "b"], ["z"], 10) == 0.0


def test_mrr_and_ndcg() -> None:
    assert mrr_at_k(["x", "gold"], ["gold"], 10) == 0.5
    assert ndcg_at_k(["gold"], ["gold"], 10) == 1.0


def test_groundedness_abstain() -> None:
    verdict = groundedness_verdict(
        coverage=0.2,
        entailment_labels=["unrelated"],
        confidence=0.01,
    )
    assert verdict == "unsupported"


def test_groundedness_all_unrelated_is_unsupported() -> None:
    """Vary only labels: all-unrelated must not ground when coverage/conf pass."""
    kwargs = {"coverage": 0.95, "confidence": 0.9}
    assert (
        groundedness_verdict(entailment_labels=["unrelated", "unrelated"], **kwargs)
        == "unsupported"
    )
    assert groundedness_verdict(entailment_labels=["entailed", "entailed"], **kwargs) == "grounded"
    assert (
        groundedness_verdict(entailment_labels=["entailed", "contradicted"], **kwargs)
        == "unsupported"
    )


def test_citation_coverage() -> None:
    cites = [
        CitationSpan(
            chunk_id="c1",
            document_version_id="v1",
            document_title="Doc",
            cited_text="span",
            start_char=0,
            end_char=4,
            answer_sentence_idx=0,
        )
    ]
    cov = citation_coverage("The policy requires review. Additional note.", cites)
    assert 0.0 < cov <= 1.0
