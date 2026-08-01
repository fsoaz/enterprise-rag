from __future__ import annotations

from llm.client import RetrievedChunk, extractive_fallback


def test_extractive_fallback_emits_sources_without_sentence_bindings() -> None:
    result = extractive_fallback(
        [
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                document_title="Policy",
                body="Employees receive 20 vacation days.",
                score=0.9,
            )
        ]
    )

    assert result.stop_reason == "extractive_fallback"
    assert result.model == "extractive-fallback"
    assert [citation.answer_sentence_idx for citation in result.citations] == [-1]


def test_extractive_fallback_truncates_cited_text_on_word_boundary() -> None:
    body = (
        "Employees must agree vacation dates with the reporting manager in writing "
        "before booking travel or making non-refundable commitments of any kind."
    )
    # Force truncation: repeat until well over 200 chars.
    body = f"{body} {body}"
    assert len(body) > 200

    result = extractive_fallback(
        [
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                document_title="Policy",
                body=body,
                score=0.9,
            )
        ]
    )

    cited = result.citations[0].cited_text
    assert cited.endswith("…")
    assert len(cited) <= 201
    assert cited[:-1] in body
