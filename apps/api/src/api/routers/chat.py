from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from api.deps.auth import CurrentUser
from api.deps.db import get_db_session
from api.services.chat import run_chat
from api.settings import Settings, get_settings
from domain.types import RetrievalStrategy

router = APIRouter(prefix="/chat", tags=["chat"])

StrategyLiteral = Literal["dense_only", "lexical_only", "hybrid_rrf", "hybrid_rerank"]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    stream: bool = True
    strategy: StrategyLiteral = "hybrid_rrf"


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/completions")
async def chat_completions(
    body: ChatRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        async for evt in run_chat(
            session,
            tenant_id=user.tenant_id,
            user_id=user.id,
            question=body.question,
            strategy=RetrievalStrategy(body.strategy),
            anthropic_api_key=settings.anthropic_api_key,
            stream=body.stream,
        ):
            yield _sse(evt["event"], evt["data"])

    return StreamingResponse(event_stream(), media_type="text/event-stream")
