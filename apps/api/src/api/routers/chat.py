from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from api.deps.auth import CurrentUser
from api.deps.db import get_db_session
from api.deps.limits import assert_within_budget, enforce_rate_limit
from api.services.chat import run_chat
from api.settings import Settings, get_settings
from db.models import Query, QueryCitation
from domain.errors import NotFoundError
from domain.types import RetrievalStrategy
from llm.client import ConversationMessage
from retrieval.pipeline import retrieve

router = APIRouter(tags=["chat"])

StrategyLiteral = Literal["dense_only", "lexical_only", "hybrid_rrf", "hybrid_rerank"]


class ChatMessage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=16_000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str | None = Field(default=None, min_length=1, max_length=8000)
    messages: list[ChatMessage] | None = Field(default=None, min_length=1, max_length=12)
    stream: bool = True
    strategy: StrategyLiteral = "hybrid_rrf"

    @model_validator(mode="after")
    def validate_input(self) -> ChatRequest:
        if self.question is None and not self.messages:
            raise ValueError("Either question or messages is required")
        if self.messages:
            if self.messages[0].role != "user":
                raise ValueError("messages must start with a user message")
            if self.messages[-1].role != "user":
                raise ValueError("messages must end with a user message")
            if any(
                current.role == previous.role
                for previous, current in zip(self.messages, self.messages[1:], strict=False)
            ):
                raise ValueError("message roles must alternate")
            if any(
                message.role == "user" and len(message.content) > 8000 for message in self.messages
            ):
                raise ValueError("user messages must be at most 8000 characters")
            if sum(len(message.content) for message in self.messages) > 64_000:
                raise ValueError("message history must be at most 64000 characters")
        return self

    def resolved_question(self) -> str:
        if self.messages:
            return self.messages[-1].content
        assert self.question is not None
        return self.question

    def conversation_history(self) -> list[ConversationMessage]:
        if not self.messages:
            return []
        return [
            ConversationMessage(role=message.role, content=message.content)
            for message in self.messages[:-1][-6:]
        ]


class QueryOut(BaseModel):
    id: str
    question: str
    answer_text: str | None
    groundedness_verdict: str | None
    citation_coverage: float | None
    retrieved_chunk_ids: list[str]
    citations: list[dict[str, object]]


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat/completions")
async def chat_completions(
    body: ChatRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> StreamingResponse:
    # After body validation so malformed payloads (422) do not consume quota.
    await enforce_rate_limit(
        user,
        settings,
        response,
        scope="chat",
        limit_attr="chat_rate_limit_per_minute",
    )
    question = body.resolved_question()
    history = body.conversation_history()
    # Checked before the stream opens so an over-budget tenant gets a 429 rather
    # than a 200 whose body turns out to be an error event.
    await assert_within_budget(session, tenant_id=user.tenant_id, settings=settings)
    # Do not send SSE headers until retrieval is known to be available.  A domain
    # error at this point is still converted to the normal RFC 7807 response.
    retrieval = await retrieve(
        session,
        tenant_id=user.tenant_id,
        user_id=user.id,
        query=question,
        strategy=RetrievalStrategy(body.strategy),
    )

    async def event_stream() -> AsyncIterator[str]:
        async for evt in run_chat(
            session,
            tenant_id=user.tenant_id,
            user_id=user.id,
            question=question,
            conversation_history=history,
            strategy=RetrievalStrategy(body.strategy),
            anthropic_api_key=settings.anthropic_api_key,
            stream=body.stream,
            retrieval_result=retrieval,
        ):
            yield _sse(evt["event"], evt["data"])

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=dict(response.headers)
    )


@router.get("/queries/{query_id}", response_model=QueryOut)
async def get_query(
    query_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> QueryOut:
    query = await session.get(Query, query_id)
    if query is None or query.tenant_id != user.tenant_id:
        raise NotFoundError("Query not found")
    if "admin" not in user.roles and query.user_id != user.user_id:
        raise NotFoundError("Query not found")
    citations = (
        await session.scalars(select(QueryCitation).where(QueryCitation.query_id == query.id))
    ).all()
    return QueryOut(
        id=str(query.id),
        question=query.question,
        answer_text=query.answer_text,
        groundedness_verdict=query.groundedness_verdict,
        citation_coverage=query.citation_coverage,
        retrieved_chunk_ids=[str(chunk_id) for chunk_id in query.retrieved_chunk_ids or []],
        citations=[
            {
                "chunk_id": str(citation.chunk_id),
                "document_version_id": str(citation.document_version_id),
                "cited_text": citation.cited_text,
                "start_char": citation.start_char,
                "end_char": citation.end_char,
                "answer_sentence_idx": citation.answer_sentence_idx,
            }
            for citation in citations
        ],
    )
