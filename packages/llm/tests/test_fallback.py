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
    assert [citation.answer_sentence_idx for citation in result.citations] == [-1]
