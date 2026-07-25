from __future__ import annotations

from db import models as _models
from db.base import Base
from db.session import get_engine, get_session_factory, set_tenant_context, tenant_session

# Re-export models so `import db` exposes the metadata graph for Alembic.
__all__ = [
    "Base",
    "get_engine",
    "get_session_factory",
    "models",
    "set_tenant_context",
    "tenant_session",
]

models = _models
