from __future__ import annotations

import hashlib
import time
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import CostLedger, Document, Query, QueryCitation
from domain.types import RetrievalStrategy
from llm.client import AnthropicClient, RetrievedChunk, extractive_fallback
from llm.groundedness import (
    citation_coverage,
    groundedness_verdict,
    retrieval_confidence,
    should_abstain,
)
from llm.models import PRIMARY_MODEL
from retrieval.pipeline import retrieve


async def _titles_for_docs(session: AsyncSession, doc_ids: list[UUID]) -> dict[UUID, str]:
    if not doc_ids:
        return {}
    rows = await session.execute(
        select(Document.id, Document.title).where(Document.id.in_(doc_ids))
    )
    return {row.id: row.title for row in rows.all()}


def _use_live_llm(api_key: str) -> bool:
    return bool(api_key) and not api_key.endswith("replace-me") and api_key.startswith("sk-")


_ANSWER_CHUNK_CHARS = 96


def _chunk_answer(text: str) -> Iterator[str]:
    """Split the verified answer into token-sized pieces for the SSE stream."""
    for start in range(0, len(text), _ANSWER_CHUNK_CHARS):
        yield text[start : start + _ANSWER_CHUNK_CHARS]


async def run_chat(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    question: str,
    strategy: RetrievalStrategy = RetrievalStrategy.HYBRID_RRF,
    anthropic_api_key: str = "",
    stream: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE event dicts for chat completions."""
    started = time.perf_counter()
    yield {"event": "status", "data": {"stage": "retrieving"}}

    result = await retrieve(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        query=question,
        strategy=strategy,
    )
    titles = await _titles_for_docs(session, [h.document_id for h in result.hits])
    chunks = [
        RetrievedChunk(
            chunk_id=str(h.chunk_id),
            document_version_id=str(h.document_version_id),
            document_title=titles.get(h.document_id, "Document"),
            body=h.body,
            score=h.score,
        )
        for h in result.hits
    ]
    scores = [h.score for h in result.hits]
    confidence = retrieval_confidence(scores)

    yield {"event": "status", "data": {"stage": "generating"}}

    generation = None
    if chunks and _use_live_llm(anthropic_api_key):
        client = AnthropicClient(anthropic_api_key)
        if stream:
            # Consume the model stream but do NOT forward tokens yet. The
            # groundedness verdict is only computable once the full answer and its
            # citations exist; forwarding first and abstaining afterwards would
            # leave the ungrounded answer on the user's screen with a retraction
            # appended, which defeats the abstention gate entirely.
            answer_parts: list[str] = []
            citations_acc: list[Any] = []
            usage_data: dict[str, Any] = {}
            async for evt in client.stream_cited_answer(question=question, chunks=chunks):
                if evt["event"] == "token":
                    answer_parts.append(evt["data"]["text"])
                elif evt["event"] == "citation":
                    citations_acc.append(evt["data"])
                elif evt["event"] == "usage":
                    usage_data = evt["data"]
                elif evt["event"] == "error":
                    generation = extractive_fallback(chunks)
                    break
                elif evt["event"] == "done":
                    from llm.client import CitationSpan, GenerationResult

                    generation = GenerationResult(
                        answer_text="".join(answer_parts).strip()
                        or str(evt["data"].get("answer_text", "")),
                        citations=[
                            CitationSpan(
                                chunk_id=c["chunk_id"],
                                document_version_id=c["document_version_id"],
                                document_title=c.get("document_title", ""),
                                cited_text=c.get("cited_text", ""),
                                start_char=int(c.get("start_char", 0)),
                                end_char=int(c.get("end_char", 0)),
                                answer_sentence_idx=int(c.get("answer_sentence_idx", 0)),
                            )
                            for c in citations_acc
                        ],
                        model=str(usage_data.get("model", PRIMARY_MODEL)),
                        input_tokens=int(usage_data.get("input_tokens", 0)),
                        output_tokens=int(usage_data.get("output_tokens", 0)),
                        cache_read_input_tokens=int(usage_data.get("cache_read_input_tokens", 0)),
                        stop_reason="end_turn",
                        cost_usd=Decimal(str(usage_data.get("cost_usd", "0"))),
                    )
        else:
            generation = await client.generate_cited_answer(question=question, chunks=chunks)
    else:
        generation = extractive_fallback(chunks) if chunks else extractive_fallback([])

    if generation is None:
        # Stream ended without a terminal done/error event.
        generation = extractive_fallback(chunks)

    # Build synthetic citations for extractive path when none from model
    if not generation.citations and chunks:
        from llm.client import CitationSpan

        generation = type(generation)(
            answer_text=generation.answer_text,
            citations=[
                CitationSpan(
                    chunk_id=c.chunk_id,
                    document_version_id=c.document_version_id,
                    document_title=c.document_title,
                    cited_text=c.body[:240],
                    start_char=0,
                    end_char=min(240, len(c.body)),
                    answer_sentence_idx=i,
                )
                for i, c in enumerate(chunks[:3])
            ],
            model=generation.model,
            input_tokens=generation.input_tokens,
            output_tokens=generation.output_tokens,
            cache_read_input_tokens=generation.cache_read_input_tokens,
            stop_reason=generation.stop_reason,
            cost_usd=generation.cost_usd,
        )

    coverage = citation_coverage(generation.answer_text, generation.citations)
    # Skip live entailment judge when using extractive / stub key (cost + key)
    labels: list[str] = ["entailed"] * len(generation.citations) if generation.citations else []
    if (
        _use_live_llm(anthropic_api_key)
        and generation.citations
        and generation.stop_reason != "extractive_fallback"
    ):
        client = AnthropicClient(anthropic_api_key)
        pairs = [(generation.answer_text, c.cited_text) for c in generation.citations[:8]]
        labels = await client.judge_entailment(pairs)

    verdict = groundedness_verdict(
        coverage=coverage,
        entailment_labels=labels,
        confidence=confidence if chunks else 0.0,
    )
    abstain = should_abstain(verdict) or not chunks

    answer_text = generation.answer_text
    if abstain:
        answer_text = "I could not find support for this in the documents you have access to."
        if chunks:
            answer_text += " Closest sources are attached as citations."
        verdict = "unsupported"

    # Single emission point for the answer, reached only after the verdict is known.
    # `answer_text` is either the verified generation or the abstention message.
    for piece in _chunk_answer(answer_text):
        yield {"event": "token", "data": {"text": piece}}
    for cite in generation.citations:
        yield {
            "event": "citation",
            "data": {
                "answer_sentence_idx": cite.answer_sentence_idx,
                "chunk_id": cite.chunk_id,
                "document_version_id": cite.document_version_id,
                "cited_text": cite.cited_text,
                "start_char": cite.start_char,
                "end_char": cite.end_char,
                "document_title": cite.document_title,
                "staleness": "fresh",
            },
        }

    query_id = uuid4()
    latency_ms = int((time.perf_counter() - started) * 1000)
    prompt_hash = hashlib.sha256(question.encode()).hexdigest()[:32]

    session.add(
        Query(
            id=query_id,
            tenant_id=tenant_id,
            user_id=user_id,
            question=question,
            language="pt" if any(ch in question.lower() for ch in "ãáàçéíóú") else "en",
            strategy=result.strategy,
            retrieved_chunk_ids=[h.chunk_id for h in result.hits],
            rerank_scores=scores or None,
            answer_text=answer_text,
            groundedness_verdict=verdict,
            citation_coverage=coverage,
            latency_ms=latency_ms,
            model=generation.model,
            prompt_hash=prompt_hash,
            acl_version=result.acl_version,
        )
    )
    for cite in generation.citations:
        session.add(
            QueryCitation(
                tenant_id=tenant_id,
                query_id=query_id,
                chunk_id=UUID(cite.chunk_id),
                document_version_id=UUID(cite.document_version_id),
                cited_text=cite.cited_text or "",
                start_char=cite.start_char,
                end_char=cite.end_char,
                answer_sentence_idx=cite.answer_sentence_idx,
            )
        )
    if generation.input_tokens or generation.output_tokens or generation.cost_usd:
        session.add(
            CostLedger(
                tenant_id=tenant_id,
                query_id=query_id,
                purpose="generation",
                model=generation.model,
                input_tokens=generation.input_tokens,
                output_tokens=generation.output_tokens,
                cache_read_input_tokens=generation.cache_read_input_tokens,
                cache_creation_input_tokens=0,
                latency_ms=latency_ms,
                computed_cost_usd=generation.cost_usd,
                price_table_version="v0",
            )
        )
    await session.flush()

    yield {
        "event": "usage",
        "data": {
            "input_tokens": generation.input_tokens,
            "output_tokens": generation.output_tokens,
            "cache_read_input_tokens": generation.cache_read_input_tokens,
            "cost_usd": str(generation.cost_usd),
            "model": generation.model,
        },
    }
    yield {
        "event": "verdict",
        "data": {"groundedness": verdict, "citation_coverage": coverage},
    }
    yield {"event": "done", "data": {"query_id": str(query_id)}}
