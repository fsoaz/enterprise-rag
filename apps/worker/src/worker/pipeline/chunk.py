"""Fixed-token chunking (~512 tokens, 64 overlap) with section/language heuristics."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from domain.text import detect_supported_language
from domain.types import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_TOKENS
from worker.pipeline.parse import ParsedDocument

# Approx tokens ≈ words for Latin scripts; chars/4 as fallback for dense text.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
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
    if any(marker in lower for marker in ("<|im_start|>", "<|system|>", "[inst]", "<<sys>>")):
        score = 0.95
    if "jailbreak" in lower or "prompt injection" in lower:
        score = max(score, 0.95)

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
        score = max(score, 0.9)

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
        score = max(score, 0.85)

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
