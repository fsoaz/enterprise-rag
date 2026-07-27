"""Production and deterministic-test inference backends."""

from __future__ import annotations

import hashlib
import importlib
import math
import os
from threading import Lock
from typing import Any, Protocol, cast

EMBEDDING_DIM = 1024
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


class InferenceBackend(Protocol):
    @property
    def embedding_model(self) -> str: ...

    @property
    def rerank_model(self) -> str: ...

    def embed(self, texts: list[str], *, mode: str) -> list[list[float]]: ...

    def rerank(self, query: str, documents: list[str]) -> list[float]: ...


def stub_vector(text: str) -> list[float]:
    """Return a deterministic non-zero unit vector for isolated tests."""
    seed = text.encode("utf-8")
    raw = bytearray()
    counter = 0
    while len(raw) < EMBEDDING_DIM:
        raw.extend(hashlib.sha256(counter.to_bytes(4, "big") + seed).digest())
        counter += 1
    values = [(byte / 127.5) - 1.0 for byte in raw[:EMBEDDING_DIM]]
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0.0:  # pragma: no cover - impossible for SHA-256 output
        values[0], norm = 1.0, 1.0
    return [value / norm for value in values]


class StubBackend:
    """Deterministic backend used only when ``INFERENCE_BACKEND=stub``."""

    embedding_model = "deterministic-hash-test-stub"
    rerank_model = "identity-rerank-test-stub"

    def embed(self, texts: list[str], *, mode: str) -> list[list[float]]:
        del mode
        return [stub_vector(text) for text in texts]

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        del query
        count = max(len(documents), 1)
        return [1.0 - (index / count) for index in range(len(documents))]


class BgeBackend:
    """BGE-M3 embeddings plus the multilingual v2-M3 cross-encoder."""

    def __init__(self) -> None:
        try:
            sentence_transformers = importlib.import_module("sentence_transformers")
        except ImportError as exc:  # pragma: no cover - production dependency
            raise RuntimeError(
                "INFERENCE_BACKEND=bge requires the inference 'models' extra; install "
                "with `uv sync --package enterprise-rag-inference --extra models`"
            ) from exc

        self.embedding_model = os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip()
        self.rerank_model = os.environ.get("RERANK_MODEL", DEFAULT_RERANK_MODEL).strip()
        device = os.environ.get("INFERENCE_DEVICE", "cpu").strip()
        self._batch_size = _positive_int_env("INFERENCE_BATCH_SIZE", default=16)
        self._lock = Lock()

        # The official model cards support these Sentence Transformers APIs.
        # Remote model code remains disabled for supply-chain safety.
        self._embedder = sentence_transformers.SentenceTransformer(
            self.embedding_model,
            device=device,
            trust_remote_code=False,
        )
        self._reranker = sentence_transformers.CrossEncoder(
            self.rerank_model,
            device=device,
            trust_remote_code=False,
        )

    def embed(self, texts: list[str], *, mode: str) -> list[list[float]]:
        del mode  # BGE-M3 uses one multilingual space for queries and passages.
        with self._lock:
            encoded = self._embedder.encode(
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        vectors = cast(Any, encoded).tolist()
        if any(len(vector) != EMBEDDING_DIM for vector in vectors):
            raise RuntimeError(
                f"{self.embedding_model} violated the {EMBEDDING_DIM}-dimension contract"
            )
        return cast(list[list[float]], vectors)

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        pairs = [(query, document) for document in documents]
        with self._lock:
            predicted = self._reranker.predict(
                pairs,
                batch_size=self._batch_size,
                show_progress_bar=False,
            )
        raw = cast(Any, predicted).tolist()
        if isinstance(raw, float):
            return [raw]
        return [float(score) for score in raw]


def _positive_int_env(name: str, *, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


_backend: InferenceBackend | None = None
_backend_lock = Lock()


def get_backend() -> InferenceBackend:
    global _backend
    if _backend is not None:
        return _backend
    with _backend_lock:
        if _backend is not None:
            return _backend
        backend_name = os.environ.get("INFERENCE_BACKEND", "bge").strip().lower()
        if backend_name == "bge":
            _backend = BgeBackend()
        elif backend_name == "stub":
            _backend = StubBackend()
        else:
            raise RuntimeError("INFERENCE_BACKEND must be either 'bge' or 'stub'")
        return _backend


def reset_backend() -> None:
    """Clear the process backend for tests; production configuration is immutable."""
    global _backend
    with _backend_lock:
        _backend = None
