from __future__ import annotations

from functools import partial
from typing import Literal

import anyio
from fastapi import APIRouter
from pydantic import BaseModel, Field

from inference.backend import EMBEDDING_DIM, get_backend

router = APIRouter(prefix="/v1", tags=["embed"])


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=128)
    mode: Literal["query", "passage"] = "passage"


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    model: str
    dim: int


@router.post("/embed", response_model=EmbedResponse)
async def embed(body: EmbedRequest) -> EmbedResponse:
    backend = get_backend()
    vectors = await anyio.to_thread.run_sync(partial(backend.embed, body.texts, mode=body.mode))
    return EmbedResponse(vectors=vectors, model=backend.embedding_model, dim=EMBEDDING_DIM)
