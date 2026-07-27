from __future__ import annotations

from uuid import uuid4

from retrieval.lexical import LEXICAL_MIN_EVIDENCE_TERMS, LEXICAL_MIN_RANK, LexicalHit, _or_tsquery


def _hit(matched_terms: int) -> LexicalHit:
    return LexicalHit(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        body="body",
        score=1.0,
        primary_score=1.0,
        matched_terms=matched_terms,
    )


def test_question_terms_are_or_combined_for_fts() -> None:
    assert _or_tsquery("What is the password rotation period?") == (
        "What OR is OR the OR password OR rotation OR period"
    )


def test_fts_query_builder_drops_operator_punctuation() -> None:
    assert _or_tsquery("password | rotation") == "password OR rotation"


def test_lexical_evidence_floor_is_positive() -> None:
    assert LEXICAL_MIN_RANK > 0


def test_single_shared_term_is_not_evidence() -> None:
    # One incidental common word ("next") outranks any workable rank floor while
    # saying nothing about relevance, so a single match must not qualify.
    assert _hit(1).is_evidence is False


def test_two_shared_terms_are_evidence() -> None:
    assert _hit(LEXICAL_MIN_EVIDENCE_TERMS).is_evidence is True


def test_unmatched_chunk_is_not_evidence() -> None:
    assert _hit(0).is_evidence is False
