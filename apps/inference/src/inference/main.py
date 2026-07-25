from __future__ import annotations

import os

from fastapi import Depends, FastAPI

from inference.deps import require_service_token, warn_if_unauthenticated
from inference.routers import embed, rerank
from observability.logging import configure_logging

configure_logging(os.environ.get("LOG_LEVEL", "INFO"))

app = FastAPI(title="Enterprise RAG Inference", version="0.1.0")

warn_if_unauthenticated()

app.include_router(embed.router, dependencies=[Depends(require_service_token)])
app.include_router(rerank.router, dependencies=[Depends(require_service_token)])
