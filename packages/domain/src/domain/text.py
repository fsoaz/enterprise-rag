"""Text sanitation and content sniffing shared by upload validation and parsing.

Lives in ``domain`` because both the API (which validates uploads) and the worker
(which parses them) need the same rules, and the import contracts forbid the API
from reaching into worker modules.
"""

from __future__ import annotations

# Postgres rejects U+0000 in `text` columns outright: a chunk body containing one
# fails the INSERT with `invalid byte sequence for encoding "UTF8": 0x00`, which
# aborts ingest well after the upload has been accepted.
NUL = "\x00"

# Bytes that legitimately appear in plain text: tab, newline, carriage return,
# form feed, and everything from space upward.
_TEXT_BYTES = bytes({0x09, 0x0A, 0x0D, 0x0C}) + bytes(range(0x20, 0x100))
_SNIFF_WINDOW = 8192
_MAX_CONTROL_RATIO = 0.10

PDF_MAGIC = b"%PDF-"


def sanitize_text(value: str) -> str:
    """Drop characters no Postgres ``text`` column can hold.

    Only U+0000 is actually rejected; everything else round-trips, so this stays
    deliberately narrow rather than stripping arbitrary control characters and
    silently corrupting document content.
    """
    if NUL not in value:
        return value
    return value.replace(NUL, "")


def looks_like_pdf(data: bytes) -> bool:
    return data.startswith(PDF_MAGIC)


def looks_like_text(data: bytes) -> bool:
    """True when ``data`` is plausibly human-readable text rather than a binary.

    Content-based, because the declared ``Content-Type`` is attacker-controlled:
    a client could label any payload ``text/plain`` and walk straight past a
    header-only allowlist.
    """
    if not data:
        return False
    window = data[:_SNIFF_WINDOW]
    if NUL.encode() in window:
        return False
    control = sum(1 for byte in window if byte not in _TEXT_BYTES)
    if control / len(window) > _MAX_CONTROL_RATIO:
        return False
    try:
        window.decode("utf-8")
    except UnicodeDecodeError:
        # Truncating mid-codepoint is expected; only a wholesale failure matters.
        try:
            data[: max(0, _SNIFF_WINDOW - 4)].decode("utf-8")
        except UnicodeDecodeError:
            return True  # latin-1 fallback territory, still text
    return True


def decode_text(data: bytes) -> str:
    """Decode bytes to text (utf-8, latin-1 fallback), normalized and NUL-free."""
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError:
        decoded = data.decode("latin-1")
    decoded = decoded.replace("\r\n", "\n").replace("\r", "\n")
    return sanitize_text(decoded)
