from __future__ import annotations

import hashlib
import math
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

# Dim is part of the inference contract; keep local to avoid importing packages.
EMBEDDING_DIM = 1024
_BYTES_PER_DIGEST = 32

router = APIRouter(prefix="/v1", tags=["embed"])


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    mode: Literal["query", "passage"] = "passage"


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    model: str
    dim: int


def stub_vector(text: str) -> list[float]:
    """Deterministic unit vector derived from the text.

    Must never return the zero vector: pgvector's ``<=>`` (cosine distance) is
    undefined against a zero vector and yields NaN, which would poison ordering,
    RRF fusion, and retrieval confidence downstream. Query and passage share one
    encoding so identical text scores 1.0 — enough to exercise the wiring until
    real BGE-M3 weights land (T-105).
    """
    seed = text.encode("utf-8")
    raw = bytearray()
    counter = 0
    while len(raw) < EMBEDDING_DIM:
        raw.extend(hashlib.sha256(counter.to_bytes(4, "big") + seed).digest())
        counter += 1
    values = [(byte / 127.5) - 1.0 for byte in raw[:EMBEDDING_DIM]]
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0.0:  # pragma: no cover - impossible for sha256 output
        values[0], norm = 1.0, 1.0
    return [v / norm for v in values]


@router.post("/embed", response_model=EmbedResponse)
async def embed(body: EmbedRequest) -> EmbedResponse:
    # Stub: deterministic hashed unit vectors. Real BGE-M3 lands in Phase 1 (T-105).
    vectors = [stub_vector(text) for text in body.texts]
    return EmbedResponse(vectors=vectors, model="BAAI/bge-m3-stub", dim=EMBEDDING_DIM)
