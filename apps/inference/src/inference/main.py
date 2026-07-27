from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from fastapi import Depends, FastAPI

from inference.backend import get_backend
from inference.deps import require_service_token, warn_if_unauthenticated
from inference.routers import embed, rerank
from observability.logging import configure_logging

configure_logging(os.environ.get("LOG_LEVEL", "INFO"))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Fail startup if real weights cannot load. A silent hash fallback would make
    # readiness green while removing semantic and cross-lingual retrieval.
    await anyio.to_thread.run_sync(get_backend)
    yield


app = FastAPI(title="Enterprise RAG Inference", version="0.1.0", lifespan=lifespan)

warn_if_unauthenticated()

app.include_router(embed.router, dependencies=[Depends(require_service_token)])
app.include_router(rerank.router, dependencies=[Depends(require_service_token)])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    # Lifespan prevents traffic until both configured models have loaded.
    return {"status": "ready"}
