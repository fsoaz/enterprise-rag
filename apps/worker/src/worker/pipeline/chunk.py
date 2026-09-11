"""Deterministic chunking strategies with section and language heuristics."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from domain.text import detect_supported_language
from domain.types import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_TOKENS,
    DEFAULT_CHUNKING_STRATEGY,
    INJECTION_RISK_LINGUISTIC,
    ChunkingStrategy,
)
from worker.pipeline.parse import ParsedDocument

# Approx tokens ≈ words for Latin scripts; chars/4 as fallback for dense text.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_PARAGRAPH_RE = re.compile(r"\S.*?(?=\n\s*\n|\Z)", re.DOTALL)
_WORD_RE = re.compile(r"\S+")


@dataclass(slots=True)
class TextChunk:
    ordinal: int
    body: str
    token_count: int
    page_from: int | None
    page_to: int | None
    section_path: str | None
    language: str
    injection_risk: float


def estimate_tokens(text: str) -> int:
    words = _WORD_RE.findall(text)
    if words:
        return max(1, len(words))
    return max(1, (len(text) + 3) // 4)


def detect_language(text: str) -> str:
    """Compatibility wrapper around the shared user/document detector."""
    return detect_supported_language(text)


def score_injection_risk(text: str) -> float:
    """Score structural instruction override and exfiltration language.

    This remains a conservative deterministic classifier, not a claim of general
    prompt-injection immunity.  It normalizes accents and simple whitespace
    obfuscation, and combines multilingual action/target concepts so paraphrases do
    not depend on one exact 13-entry phrase list.

    Only structural chat-template markers score at or above the hard-block
    threshold. Linguistic patterns cap in the flag band so policy prose that
    shares vocabulary stays retrievable and reaches the model as [UNTRUSTED].
    """
    normalized = unicodedata.normalize("NFKD", text.casefold())
    lower = "".join(char for char in normalized if not unicodedata.combining(char))
    lower = re.sub(r"\s+", " ", lower)
    # "i g n o r e" / "r e v e a l" is a common low-effort filter bypass.
    lower = re.sub(
        r"(?<!\w)(?:[a-z]\s+){3,}[a-z](?!\w)",
        lambda match: match.group(0).replace(" ", ""),
        lower,
    )

    score = 0.0
    # Hard-block band: markers with no benign reading in a document corpus.
    if any(marker in lower for marker in ("<|im_start|>", "<|system|>", "[inst]", "<<sys>>")):
        score = 0.95

    if "jailbreak" in lower or "prompt injection" in lower:
        score = max(score, INJECTION_RISK_LINGUISTIC)

    override_action = re.search(
        r"\b(ignore|disregard|forget|bypass|override|desconsidere|ignora|olvide|"
        r"oublie[rz]?|ignorez|vergiss|ignoriere)\b",
        lower,
    )
    authority_target = re.search(
        r"\b(previous|prior|above|all|system|developer|instructions?|rules?|policy|"
        r"instrucoes?|orientacoes?|anteriores?|todas?|sistema|"
        r"instrucciones?|reglas?|consignes?|precedentes?|regles?|"
        r"anweisungen?|vorherigen?)\b",
        lower,
    )
    if override_action and authority_target:
        score = max(score, INJECTION_RISK_LINGUISTIC)

    exfil_action = re.search(
        r"\b(reveal|print|show|output|repeat|expose|mostre|revele|imprima|"
        r"muestre|revela|affiche[rz]?|revele[rz]?|zeige)\b",
        lower,
    )
    protected_target = re.search(
        r"\b(system prompt|hidden (?:prompt|instructions?)|your instructions?|"
        r"configuration|secrets?|prompt do sistema|instrucoes? ocultas?|configuracao|"
        r"prompt del sistema|instrucciones? ocultas?|invite systeme|"
        r"consignes? cachees?|system[- ]prompt|versteckte anweisungen?)\b",
        lower,
    )
    safe_negation = re.search(
        r"\b(?:must\s+never|never|do\s+not|dont|nao|nunca|no|ne\s+pas|nicht)\s+"
        r"(?:reveal|print|show|output|expose|mostre|revele|imprima|muestre|revela|"
        r"affiche[rz]?|revele[rz]?|zeige)\b",
        lower,
    )
    if exfil_action and protected_target and not safe_negation:
        score = max(score, INJECTION_RISK_LINGUISTIC)

    if re.search(
        r"\b(you are now|act as|a partir de agora|finja que|ahora eres|"
        r"actua como|agis comme|du bist jetzt)\b",
        lower,
    ):
        score = max(score, 0.6)
    # Dense instruction-like imperatives in short chunks.
    if re.search(r"\b(always|never|must)\s+(say|answer|respond|output)\b", lower):
        score = max(score, 0.5)
    return min(1.0, score)


def _section_spans(text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, section_path) spans covering the whole document."""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [(0, len(text), "")]

    stack: list[tuple[int, str]] = []
    spans: list[tuple[int, int, str]] = []

    # Preamble before first heading.
    if matches[0].start() > 0:
        spans.append((0, matches[0].start(), ""))

    for i, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        path = " / ".join(t for _, t in stack)
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        spans.append((start, end, path))
    return spans


def _page_for_offset(doc: ParsedDocument, offset: int) -> int | None:
    if not doc.pages:
        return None
    # Map character offset onto concatenated page texts with "\n\n" join.
    cursor = 0
    for page in doc.pages:
        length = len(page.text)
        if offset <= cursor + length:
            return page.page_no
        cursor += length + 2  # account for "\n\n"
    return doc.pages[-1].page_no


def _chunk_from_range(
    doc: ParsedDocument,
    *,
    section_text: str,
    section_start: int,
    start: int,
    end: int,
    section_path: str,
    ordinal: int,
) -> TextChunk | None:
    body = section_text[start:end].strip()
    if not body:
        return None
    absolute_offset = section_start + start
    page = _page_for_offset(doc, absolute_offset)
    return TextChunk(
        ordinal=ordinal,
        body=body,
        token_count=estimate_tokens(body),
        page_from=page,
        page_to=page,
        section_path=section_path or None,
        language=detect_language(body),
        injection_risk=score_injection_risk(body),
    )


def _validate_options(target_tokens: int, overlap_tokens: int) -> None:
    if target_tokens < 1:
        raise ValueError("target_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be non-negative and smaller than target_tokens")


def _chunk_fixed_token(
    doc: ParsedDocument,
    *,
    target_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Split each heading section into overlapping word windows."""
    text = doc.text.strip()
    if not text:
        return []

    sections = _section_spans(text)
    chunks: list[TextChunk] = []
    ordinal = 0

    for sec_start, sec_end, section_path in sections:
        section_text = text[sec_start:sec_end].strip()
        if not section_text:
            continue
        words = list(_WORD_RE.finditer(section_text))
        if not words:
            continue

        step = max(1, target_tokens - overlap_tokens)
        i = 0
        while i < len(words):
            window = words[i : i + target_tokens]
            if not window:
                break
            start_char = window[0].start()
            end_char = window[-1].end()
            chunk = _chunk_from_range(
                doc,
                section_text=section_text,
                section_start=sec_start,
                start=start_char,
                end=end_char,
                section_path=section_path,
                ordinal=ordinal,
            )
            if chunk is None:
                i += step
                continue
            chunks.append(chunk)
            ordinal += 1
            if i + target_tokens >= len(words):
                break
            i += step

    return chunks


def _chunk_section_aware(
    doc: ParsedDocument,
    *,
    target_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Pack Markdown blocks while keeping semantic sections intact.

    Short headings and paragraphs share a chunk until the token budget is full.
    An oversized paragraph falls back to deterministic overlapping windows. Chunks
    never cross heading sections and only contain complete short paragraph blocks.
    """
    text = doc.text.strip()
    if not text:
        return []

    chunks: list[TextChunk] = []
    ordinal = 0
    step = max(1, target_tokens - overlap_tokens)
    for sec_start, sec_end, section_path in _section_spans(text):
        section_text = text[sec_start:sec_end].strip()
        if not section_text:
            continue
        blocks = list(_PARAGRAPH_RE.finditer(section_text))
        pending_start: int | None = None
        pending_end: int | None = None
        pending_tokens = 0

        def flush_pending(
            current_section_text: str = section_text,
            current_section_start: int = sec_start,
            current_section_path: str = section_path,
        ) -> None:
            nonlocal ordinal, pending_start, pending_end, pending_tokens
            if pending_start is None or pending_end is None:
                return
            chunk = _chunk_from_range(
                doc,
                section_text=current_section_text,
                section_start=current_section_start,
                start=pending_start,
                end=pending_end,
                section_path=current_section_path,
                ordinal=ordinal,
            )
            if chunk is not None:
                chunks.append(chunk)
                ordinal += 1
            pending_start = None
            pending_end = None
            pending_tokens = 0

        for block in blocks:
            block_start, block_end = block.span()
            block_text = block.group(0).strip()
            block_words = list(_WORD_RE.finditer(block_text))
            block_tokens = len(block_words)
            if block_tokens > target_tokens:
                flush_pending()
                for index in range(0, block_tokens, step):
                    window = block_words[index : index + target_tokens]
                    chunk = _chunk_from_range(
                        doc,
                        section_text=section_text,
                        section_start=sec_start,
                        start=block_start + window[0].start(),
                        end=block_start + window[-1].end(),
                        section_path=section_path,
                        ordinal=ordinal,
                    )
                    if chunk is not None:
                        chunks.append(chunk)
                        ordinal += 1
                    if index + target_tokens >= block_tokens:
                        break
                continue

            if pending_start is not None and pending_tokens + block_tokens > target_tokens:
                flush_pending()
            if pending_start is None:
                pending_start = block_start
            pending_end = block_end
            pending_tokens += block_tokens
        flush_pending()

    return chunks


def chunk_document(
    doc: ParsedDocument,
    *,
    target_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_CHUNK_OVERLAP,
    strategy: str = DEFAULT_CHUNKING_STRATEGY,
) -> list[TextChunk]:
    """Chunk a document using an explicitly named deterministic strategy."""
    _validate_options(target_tokens, overlap_tokens)
    try:
        selected = ChunkingStrategy(strategy)
    except ValueError as exc:
        raise ValueError(f"unsupported chunking strategy: {strategy}") from exc
    if selected == ChunkingStrategy.FIXED_TOKEN:
        return _chunk_fixed_token(doc, target_tokens=target_tokens, overlap_tokens=overlap_tokens)
    return _chunk_section_aware(doc, target_tokens=target_tokens, overlap_tokens=overlap_tokens)
