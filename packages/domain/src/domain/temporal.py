"""Point-in-time inputs share one UTC interpretation across API and services."""

import re
from datetime import UTC, date, datetime


def parse_as_of(value: str | date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2}))?",
            value,
        ):
            raise ValueError("as_of must be an ISO date or timezone-qualified timestamp")
        value = date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of timestamps must include a timezone")
        return value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    raise ValueError("as_of must be an ISO date or timezone-qualified timestamp")
