from datetime import UTC, datetime
from uuid import UUID

import pytest

from api.pagination import decode_cursor, encode_cursor, page_rows
from domain.errors import ValidationError


def test_cursor_round_trips_microseconds_and_uuid() -> None:
    created_at = datetime(2026, 7, 27, 12, 34, 56, 123456, tzinfo=UTC)
    item_id = UUID("11111111-2222-3333-4444-555555555555")

    position = decode_cursor(encode_cursor(created_at, item_id))

    assert position.created_at == created_at
    assert position.item_id == item_id


@pytest.mark.parametrize("cursor", ["", "not-base64!", "YWJj", "a" * 200])
def test_invalid_cursor_fails_as_validation_error(cursor: str) -> None:
    with pytest.raises(ValidationError):
        decode_cursor(cursor)


def test_next_cursor_uses_last_returned_row_only_when_more_exist() -> None:
    rows = [(datetime(2026, 7, day, tzinfo=UTC), UUID(int=day)) for day in (3, 2, 1)]
    page, cursor = page_rows(
        rows,
        limit=2,
        created_at=lambda row: row[0],
        item_id=lambda row: row[1],
    )

    assert page == rows[:2]
    assert cursor is not None
    assert decode_cursor(cursor).item_id == rows[1][1]
