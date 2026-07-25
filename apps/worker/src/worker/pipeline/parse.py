"""Parse uploaded bytes into plain text with optional page metadata."""

from __future__ import annotations

import io
from dataclasses import dataclass, field


@dataclass(slots=True)
class ParsedPage:
    page_no: int
    text: str


@dataclass(slots=True)
class ParsedDocument:
    text: str
    pages: list[ParsedPage] = field(default_factory=list)
    mime_type: str = "text/plain"


def parse_bytes(data: bytes, *, mime_type: str, filename: str | None = None) -> ParsedDocument:
    """Dispatch by MIME type / filename extension."""
    lower_name = (filename or "").lower()
    mt = (mime_type or "").lower()

    if mt == "application/pdf" or lower_name.endswith(".pdf"):
        return _parse_pdf(data)
    if mt in {"text/markdown", "text/x-markdown"} or lower_name.endswith((".md", ".markdown")):
        return _parse_text(data, mime_type="text/markdown")
    # Default: plain text (utf-8 with latin-1 fallback).
    return _parse_text(data, mime_type="text/plain")


def _parse_text(data: bytes, *, mime_type: str) -> ParsedDocument:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return ParsedDocument(text=text, pages=[ParsedPage(page_no=1, text=text)], mime_type=mime_type)


def _parse_pdf(data: bytes) -> ParsedDocument:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages: list[ParsedPage] = []
    parts: list[str] = []
    for idx, page in enumerate(reader.pages, start=1):
        raw = page.extract_text() or ""
        raw = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
        pages.append(ParsedPage(page_no=idx, text=raw))
        if raw:
            parts.append(raw)
    return ParsedDocument(text="\n\n".join(parts), pages=pages, mime_type="application/pdf")
