"""Fail-closed integration database configuration.

Integration tests mutate data by design. They must never infer their target from
the application's normal DATABASE_URL because that silently turns a developer's
working corpus into a test fixture. Only explicit TEST_DATABASE_URL values whose
database name is visibly test-designated are accepted.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit


def _async_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _database_name(url: str) -> str:
    name = urlsplit(url).path.lstrip("/").split("/", maxsplit=1)[0]
    if not name:
        raise RuntimeError("Test database URL has no database name")
    return name


def integration_database_urls() -> tuple[str, str]:
    app_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    migrate_url = os.environ.get("TEST_DATABASE_URL_MIGRATE", "").strip()
    if not app_url or not migrate_url:
        raise RuntimeError(
            "Integration tests require TEST_DATABASE_URL and "
            "TEST_DATABASE_URL_MIGRATE; run `make test-integration`"
        )

    app_name = _database_name(app_url)
    migrate_name = _database_name(migrate_url)
    if app_name != migrate_name:
        raise RuntimeError("Test app and migrate URLs must target the same database")
    if not (app_name.endswith("_test") or app_name.startswith("test_")):
        raise RuntimeError(
            f"Refusing integration database {app_name!r}; its name must end in "
            "'_test' or start with 'test_'"
        )
    return _async_url(app_url), _async_url(migrate_url)
