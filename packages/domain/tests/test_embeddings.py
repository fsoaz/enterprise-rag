from __future__ import annotations

import pytest

from domain.embeddings import embedding_model_meta


def test_embedding_model_meta_truth_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMBEDDING_MODEL_VERSION", raising=False)
    monkeypatch.setenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")

    monkeypatch.setenv("INFERENCE_BACKEND", "stub")
    assert embedding_model_meta() == ("BAAI/bge-m3", "stub-v0")

    monkeypatch.setenv("INFERENCE_BACKEND", "bge")
    assert embedding_model_meta() == ("BAAI/bge-m3", "bge-v1")

    # Stale stub label under a real backend must not mix vector spaces.
    monkeypatch.setenv("EMBEDDING_MODEL_VERSION", "stub-v0")
    assert embedding_model_meta() == ("BAAI/bge-m3", "bge-v1")

    monkeypatch.setenv("EMBEDDING_MODEL_VERSION", "custom-reembed-v2")
    assert embedding_model_meta() == ("BAAI/bge-m3", "custom-reembed-v2")

    monkeypatch.delenv("EMBEDDING_MODEL_VERSION", raising=False)
    monkeypatch.setenv("INFERENCE_BACKEND", "stub")
    monkeypatch.setenv("EMBEDDING_MODEL_VERSION", "stub-v0")
    assert embedding_model_meta() == ("BAAI/bge-m3", "stub-v0")

    monkeypatch.delenv("EMBEDDING_MODEL_VERSION", raising=False)
    monkeypatch.delenv("INFERENCE_BACKEND", raising=False)
    assert embedding_model_meta()[1] == "bge-v1"
