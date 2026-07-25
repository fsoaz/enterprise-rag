from __future__ import annotations

from domain.text import decode_text, looks_like_pdf, looks_like_text, sanitize_text


def test_sanitize_strips_nul() -> None:
    """Postgres text columns reject U+0000 outright, aborting ingest mid-pipeline."""
    assert sanitize_text("a\x00b") == "ab"
    assert sanitize_text("clean") == "clean"


def test_decode_text_removes_nul_from_binary_fallback() -> None:
    """The latin-1 fallback maps every byte, including NUL, to a character."""
    decoded = decode_text(b"MZ\x90\x00\x03 payload")
    assert "\x00" not in decoded


def test_decode_text_normalizes_newlines() -> None:
    assert decode_text(b"a\r\nb\rc") == "a\nb\nc"


def test_looks_like_text_rejects_binary() -> None:
    """Content sniffing is what stops a client mislabelling a binary as text/plain."""
    assert looks_like_text(b"# Policy\n\nPasswords rotate every 90 days.")
    assert not looks_like_text(b"MZ\x90\x00\x03\x04\x00\x00\x00")
    assert not looks_like_text(b"")


def test_looks_like_text_accepts_utf8_accents() -> None:
    assert looks_like_text("Política de segurança — revisão".encode())


def test_looks_like_pdf_matches_magic_only() -> None:
    assert looks_like_pdf(b"%PDF-1.7\n...")
    assert not looks_like_pdf(b"not a pdf")
