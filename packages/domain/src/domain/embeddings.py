"""Embedding identity shared by ingest and dense retrieval."""

from __future__ import annotations

import os


def embedding_model_meta() -> tuple[str, str]:
    """Return ``(model_name, model_version)`` for the active inference backend.

    Version is derived from ``INFERENCE_BACKEND`` so stub and BGE vectors never
    share a primary key. ``EMBEDDING_MODEL_VERSION`` remains an explicit override
    for operators who need a custom label after a re-embed.
    """
    name = (
        os.environ.get("EMBEDDING_MODEL_NAME") or os.environ.get("EMBEDDING_MODEL") or "BAAI/bge-m3"
    ).strip()
    override = (os.environ.get("EMBEDDING_MODEL_VERSION") or "").strip()
    backend = (os.environ.get("INFERENCE_BACKEND") or "bge").strip().lower() or "bge"
    derived = "stub-v0" if backend == "stub" else f"{backend}-v1"
    # A leftover stub label under a real backend silently mixes vector spaces.
    if override and not (backend != "stub" and override == "stub-v0"):
        return name, override
    return name, derived
