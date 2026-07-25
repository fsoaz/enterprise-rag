"""Fixed-token chunking (~512 tokens, 64 overlap) with section/language heuristics."""

from __future__ import annotations

import re
from dataclasses import dataclass

from domain.types import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_TOKENS
from worker.pipeline.parse import ParsedDocument

# Approx tokens ≈ words for Latin scripts; chars/4 as fallback for dense text.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_WORD_RE = re.compile(r"\S+")

_PT_MARKERS = frozenset(
    {
        "de",
        "da",
        "do",
        "das",
        "dos",
        "que",
        "não",
        "nao",
        "para",
        "com",
        "uma",
        "um",
        "os",
        "as",
        "é",
        "e",
        "em",
        "por",
        "se",
        "como",
        "mais",
        "ou",
        "ser",
        "pelo",
        "pela",
        "também",
        "tambem",
        "está",
        "esta",
        "são",
        "sao",
        "foi",
        "sobre",
        "entre",
        "quando",
        "muito",
        "já",
        "ja",
        "há",
        "ha",
        "após",
        "apos",
        "através",
        "atraves",
        "política",
        "politica",
        "segurança",
        "seguranca",
        "documento",
    }
)
_EN_MARKERS = frozenset(
    {
        "the",
        "and",
        "of",
        "to",
        "in",
        "a",
        "is",
        "for",
        "on",
        "with",
        "as",
        "by",
        "that",
        "this",
        "from",
        "are",
        "be",
        "or",
        "an",
        "at",
        "it",
        "was",
        "not",
        "have",
        "has",
        "will",
        "can",
        "their",
        "which",
        "policy",
        "security",
        "document",
        "shall",
        "must",
        "should",
    }
)


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
    """Cheap PT vs EN heuristic from function-word overlap."""
    tokens = [t.lower().strip(".,;:!?\"'()[]{}") for t in _WORD_RE.findall(text.lower())]
    if not tokens:
        return "en"
    pt = sum(1 for t in tokens if t in _PT_MARKERS)
    en = sum(1 for t in tokens if t in _EN_MARKERS)
    if pt > en:
        return "pt"
    return "en"


def score_injection_risk(text: str) -> float:
    """Simple keyword heuristic for prompt-injection patterns (architecture § 9)."""
    lower = text.lower()
    patterns = (
        ("ignore previous instructions", 0.9),
        ("ignore all instructions", 0.9),
        ("disregard previous", 0.85),
        ("system prompt", 0.7),
        ("you are now", 0.6),
        ("jailbreak", 0.95),
        ("do not follow the policy", 0.8),
        ("reveal your instructions", 0.85),
        ("ignore as instruções", 0.9),
        ("ignore as instrucoes", 0.9),
        ("prompt injection", 0.75),
        ("<|im_start|>", 0.95),
        ("[inst]", 0.7),
    )
    score = 0.0
    for needle, weight in patterns:
        if needle in lower:
            score = max(score, weight)
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


def chunk_document(
    doc: ParsedDocument,
    *,
    target_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Split document into overlapping word windows of ~target_tokens."""
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
            body = section_text[start_char:end_char].strip()
            if not body:
                i += step
                continue
            abs_offset = sec_start + start_char
            page = _page_for_offset(doc, abs_offset)
            lang = detect_language(body)
            chunks.append(
                TextChunk(
                    ordinal=ordinal,
                    body=body,
                    token_count=estimate_tokens(body),
                    page_from=page,
                    page_to=page,
                    section_path=section_path or None,
                    language=lang,
                    injection_risk=score_injection_risk(body),
                )
            )
            ordinal += 1
            if i + target_tokens >= len(words):
                break
            i += step

    return chunks
