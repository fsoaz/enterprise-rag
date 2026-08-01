from __future__ import annotations

import hashlib
import time
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Collection, CostLedger, Document, DocumentVersion, Query, QueryCitation
from domain.text import detect_supported_language
from domain.types import RetrievalStrategy
from llm.client import (
    AnthropicClient,
    ConversationMessage,
    Groundedness,
    JudgeResult,
    RetrievedChunk,
    extractive_fallback,
)
from llm.groundedness import (
    citation_coverage,
    groundedness_verdict,
    retrieval_confidence,
    should_abstain,
)
from llm.models import PRIMARY_MODEL
from retrieval.pipeline import retrieve

# Matches the `version` column of `model_prices`; ModelRegistry is the in-process
# source until that table is loaded and read.
PRICE_TABLE_VERSION = "v0"


async def _titles_for_docs(session: AsyncSession, doc_ids: list[UUID]) -> dict[UUID, str]:
    if not doc_ids:
        return {}
    rows = await session.execute(
        select(Document.id, Document.title).where(Document.id.in_(doc_ids))
    )
    return {row.id: row.title for row in rows.all()}


async def _staleness_for_versions(
    session: AsyncSession, version_ids: list[UUID]
) -> dict[UUID, str]:
    """Classify each cited version as fresh | stale | superseded.

    Previously every citation was emitted with a hardcoded ``"fresh"``, which is a
    positive claim about document currency that nothing checked — worse than
    omitting the field, because a client can act on it.

    - ``superseded``: a newer version of the document is current, so the cited text
      no longer reflects the live document.
    - ``stale``: the document is past its review interval (falling back to the
      collection default, measured from creation when it has never been reviewed).
    """
    if not version_ids:
        return {}
    rows = await session.execute(
        select(
            DocumentVersion.id,
            DocumentVersion.effective_to,
            Document.last_reviewed_at,
            Document.created_at,
            func.coalesce(
                Document.review_interval_days,
                Collection.default_review_interval_days,
            ),
        )
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(Collection, Collection.id == Document.collection_id)
        .where(DocumentVersion.id.in_(version_ids))
    )
    now = datetime.now(UTC)
    staleness: dict[UUID, str] = {}
    for version_id, effective_to, last_reviewed, created_at, interval_days in rows.all():
        if effective_to is not None:
            staleness[version_id] = "superseded"
            continue
        reference = last_reviewed or created_at
        overdue = (
            reference is not None
            and interval_days
            and now - reference > timedelta(days=int(interval_days))
        )
        if overdue:
            staleness[version_id] = "stale"
            continue
        staleness[version_id] = "fresh"
    return staleness


def _use_live_llm(api_key: str) -> bool:
    return bool(api_key) and not api_key.endswith("replace-me") and api_key.startswith("sk-")


_ANSWER_CHUNK_CHARS = 96
_DEGRADED_MESSAGES = {
    "en": {
        "fallback": "Showing source passages — synthesis unavailable.",
        "unsupported": "I could not find support for this in the documents you have access to.",
    },
    "pt": {
        "fallback": "Exibindo passagens das fontes — síntese indisponível.",
        "unsupported": "Não encontrei suporte para isso nos documentos aos quais você tem acesso.",
    },
}


def _chunk_answer(text: str) -> Iterator[str]:
    """Split the verified answer into token-sized pieces for the SSE stream."""
    remaining = text
    while remaining:
        if len(remaining) <= _ANSWER_CHUNK_CHARS:
            yield remaining
            return
        split_at = remaining.rfind(" ", 0, _ANSWER_CHUNK_CHARS + 1)
        if split_at <= 0:
            split_at = _ANSWER_CHUNK_CHARS
        yield remaining[:split_at]
        remaining = remaining[split_at:]


def fallback_verdict(*, verdict: Groundedness, has_lexical_match: bool) -> Groundedness:
    """Only show a degraded source list when FTS found query-relevant content."""
    if has_lexical_match:
        return "partial"
    return verdict


async def run_chat(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    question: str,
    conversation_history: list[ConversationMessage] | None = None,
    strategy: RetrievalStrategy = RetrievalStrategy.HYBRID_RRF,
    anthropic_api_key: str = "",
    stream: bool = False,
    retrieval_result: Any | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE event dicts for chat completions."""
    started = time.perf_counter()
    language = detect_supported_language(question)
    yield {"event": "status", "data": {"stage": "retrieving"}}

    result = retrieval_result or await retrieve(
        session, tenant_id=tenant_id, user_id=user_id, query=question, strategy=strategy
    )
    use_live_llm = _use_live_llm(anthropic_api_key)
    # Degraded mode shows only chunks backed by primary-language lexical evidence.
    # Falling back to ``result.hits`` when that evidence is empty defeats the
    # filter: a query whose terms are all stop words has no evidence at all, and
    # would otherwise be answered with dense-stub nearest neighbours.
    source_hits = result.hits if use_live_llm else result.lexical_evidence_hits
    titles = await _titles_for_docs(session, [h.document_id for h in source_hits])
    staleness = await _staleness_for_versions(session, [h.document_version_id for h in source_hits])
    chunks = [
        RetrievedChunk(
            chunk_id=str(h.chunk_id),
            document_version_id=str(h.document_version_id),
            document_title=titles.get(h.document_id, "Document"),
            body=h.body,
            score=h.score,
            is_suspect=h.is_suspect,
        )
        for h in source_hits
    ]
    scores = [h.score for h in result.hits]
    # Scores are on a strategy-specific scale; retrieval_confidence normalizes by
    # strategy so a single floor is meaningful across all four.
    confidence = retrieval_confidence(scores, strategy=result.strategy)

    yield {"event": "status", "data": {"stage": "generating"}}

    generation = None
    if chunks and use_live_llm:
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
            async for evt in client.stream_cited_answer(
                question=question,
                chunks=chunks,
                conversation_history=conversation_history,
            ):
                if evt["event"] == "token":
                    answer_parts.append(evt["data"]["text"])
                elif evt["event"] == "citation":
                    citations_acc.append(evt["data"])
                elif evt["event"] == "usage":
                    usage_data = evt["data"]
                elif evt["event"] == "error":
                    generation = extractive_fallback(
                        chunks, introduction=_DEGRADED_MESSAGES[language]["fallback"]
                    )
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
            generation = await client.generate_cited_answer(
                question=question,
                chunks=chunks,
                conversation_history=conversation_history,
            )
    else:
        generation = extractive_fallback(
            chunks, introduction=_DEGRADED_MESSAGES[language]["fallback"]
        )

    if generation is None:
        # Stream ended without a terminal done/error event.
        generation = extractive_fallback(
            chunks, introduction=_DEGRADED_MESSAGES[language]["fallback"]
        )

    # Generation is intentionally buffered until the groundedness gate has seen
    # the complete answer and citations. Expose that otherwise-invisible work as
    # a real stage instead of leaving the UI apparently frozen on "generating".
    yield {"event": "status", "data": {"stage": "verifying"}}

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
                    # A fallback is a list of sources, not a cited answer.  Do
                    # not claim it supports an invented answer sentence.
                    answer_sentence_idx=-1,
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

    is_extractive_fallback = generation.stop_reason == "extractive_fallback"
    # Fallback sources deliberately have no sentence binding, so coverage is
    # zero. Keeping it numeric preserves the established SSE and audit contract.
    coverage = (
        0.0
        if is_extractive_fallback
        else citation_coverage(generation.answer_text, generation.citations)
    )
    # Skip live entailment judge when using extractive / stub key (cost + key)
    labels: list[str] = ["unrelated"] * len(generation.citations) if generation.citations else []
    judge: JudgeResult | None = None
    if (
        _use_live_llm(anthropic_api_key)
        and generation.citations
        and generation.stop_reason != "extractive_fallback"
    ):
        client = AnthropicClient(anthropic_api_key)
        pairs = [(generation.answer_text, c.cited_text) for c in generation.citations[:8]]
        judge = await client.judge_entailment(pairs)
        labels = judge.labels

    verdict = groundedness_verdict(
        coverage=coverage or 0.0,
        entailment_labels=labels,
        confidence=confidence if chunks else 0.0,
    )
    if is_extractive_fallback:
        # A degraded source list cannot claim grounding. Dense-stub/RRF rank alone
        # is not relevance evidence; require a lexical match before showing it.
        #
        # The signal has to be the *filtered* evidence, not ``has_lexical_match``:
        # the latter is true whenever either language config matched, and the
        # secondary config does not treat the primary language's stop words as
        # stop words. A query of pure English stop words matches every English
        # chunk through the Portuguese parse, so it would certify itself.
        verdict = fallback_verdict(
            verdict=verdict, has_lexical_match=bool(result.lexical_evidence_hits)
        )
    abstain = should_abstain(verdict) or not chunks

    answer_text = generation.answer_text
    if abstain:
        answer_text = _DEGRADED_MESSAGES[language]["unsupported"]
        # Closest-neighbour passages are not evidence for an unsupported answer.
        generation = type(generation)(
            answer_text=generation.answer_text,
            citations=[],
            model=generation.model,
            input_tokens=generation.input_tokens,
            output_tokens=generation.output_tokens,
            cache_read_input_tokens=generation.cache_read_input_tokens,
            stop_reason=generation.stop_reason,
            cost_usd=generation.cost_usd,
        )
        verdict = "unsupported"

    # Single emission point for the answer, reached only after the verdict is known.
    # `answer_text` is either the verified generation or the abstention message.
    suspect_by_chunk = {c.chunk_id: c.is_suspect for c in chunks}
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
                "staleness": staleness.get(UUID(cite.document_version_id), "unknown"),
                "is_suspect": bool(suspect_by_chunk.get(cite.chunk_id, False)),
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
            language=language,
            strategy=result.strategy,
            retrieved_chunk_ids=list(
                dict.fromkeys([h.chunk_id for h in [*result.hits, *source_hits]])
            ),
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
                price_table_version=PRICE_TABLE_VERSION,
            )
        )
    # The entailment judge is a second billable model call per query; leaving it out
    # of the ledger understated real spend on every answer.
    if judge is not None and (judge.input_tokens or judge.output_tokens):
        session.add(
            CostLedger(
                tenant_id=tenant_id,
                query_id=query_id,
                purpose="judge",
                model=judge.model,
                input_tokens=judge.input_tokens,
                output_tokens=judge.output_tokens,
                cache_read_input_tokens=judge.cache_read_input_tokens,
                cache_creation_input_tokens=0,
                latency_ms=None,
                computed_cost_usd=judge.cost_usd,
                price_table_version=PRICE_TABLE_VERSION,
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
