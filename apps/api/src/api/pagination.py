"""Opaque descending keyset pagination on ``(created_at, id)``."""

from __future__ import annotations

import base64
import struct
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, or_

from domain.errors import ValidationError

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CURSOR_BYTES = 24  # signed int64 microseconds + UUID bytes


@dataclass(frozen=True, slots=True)
class CursorPosition:
    created_at: datetime
    item_id: UUID


def encode_cursor(created_at: datetime, item_id: UUID) -> str:
    aware = (
        created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at.astimezone(UTC)
    )
    delta = aware - _EPOCH
    micros = delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    payload = struct.pack(">q", micros) + item_id.bytes
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def decode_cursor(value: str) -> CursorPosition:
    try:
        padding = "=" * (-len(value) % 4)
        payload = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
        if len(payload) != _CURSOR_BYTES:
            raise ValueError
        micros = struct.unpack(">q", payload[:8])[0]
        created_at = _EPOCH + timedelta(microseconds=micros)
        item_id = UUID(bytes=payload[8:])
    except (ValueError, TypeError, struct.error, OverflowError) as exc:
        raise ValidationError(
            "Invalid pagination cursor",
            errors=[{"field": "cursor", "message": "Malformed or unsupported cursor"}],
        ) from exc
    return CursorPosition(created_at=created_at, item_id=item_id)


def apply_descending_cursor(
    stmt: Select[Any],
    *,
    created_column: Any,
    id_column: Any,
    cursor: str | None,
) -> Select[Any]:
    if cursor is None:
        return stmt
    position = decode_cursor(cursor)
    return stmt.where(
        or_(
            created_column < position.created_at,
            and_(
                created_column == position.created_at,
                id_column < position.item_id,
            ),
        )
    )


def page_rows[T](
    rows: Sequence[T],
    *,
    limit: int,
    created_at: Callable[[T], datetime],
    item_id: Callable[[T], UUID],
) -> tuple[list[T], str | None]:
    page = list(rows[:limit])
    if len(rows) <= limit or not page:
        return page, None
    last = page[-1]
    return page, encode_cursor(created_at(last), item_id(last))


def page_limit(value: int) -> int:
    """Preserve the prior clamping behavior for existing limit callers."""
    return min(max(value, 1), 200)
