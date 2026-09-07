"""Version selection does not change present-day document access controls."""

from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy.sql import ColumnElement

from db.models import DocumentVersion
from domain.temporal import parse_as_of


def version_predicate(as_of: datetime | None) -> ColumnElement[bool]:
    instant = parse_as_of(as_of)
    if instant is None:
        return DocumentVersion.effective_to.is_(None)
    return and_(
        DocumentVersion.effective_from <= instant,
        or_(DocumentVersion.effective_to.is_(None), DocumentVersion.effective_to > instant),
    )
