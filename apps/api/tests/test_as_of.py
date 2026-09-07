from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from api.routers.chat import ChatRequest
from api.routers.search import SearchRequest


@pytest.mark.parametrize("model", [ChatRequest, SearchRequest])
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("2026-07-01", datetime(2026, 7, 1, tzinfo=UTC)),
        ("2026-07-01T03:00:00+03:00", datetime(2026, 7, 1, tzinfo=UTC)),
        ("2026-07-01T00:00:00Z", datetime(2026, 7, 1, tzinfo=UTC)),
    ],
)
def test_as_of_normalizes_to_utc(model: type, value: str | None, expected: datetime | None) -> None:
    field = "question" if model is ChatRequest else "query"
    assert model.model_validate({field: "policy", "as_of": value}).as_of == expected


@pytest.mark.parametrize("model", [ChatRequest, SearchRequest])
@pytest.mark.parametrize(
    "value", ["2026-07-01T00:00:00", "yesterday", "2026-02-30", "2026-07-01X00:00:00Z", 123, ""]
)
def test_as_of_rejects_invalid_input(model: type, value: object) -> None:
    field = "question" if model is ChatRequest else "query"
    with pytest.raises(ValidationError):
        model.model_validate({field: "policy", "as_of": value})
