"""Erasure audit completeness: queries redacted and storage failures.

Revision ID: 0004_erasure_audit
Revises: 0003_keyset_pagination_indexes
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_erasure_audit"
down_revision: str | None = "0003_keyset_pagination_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS: 0001_initial uses create_all() from current models.
    op.execute(
        """
        ALTER TABLE erasure_log
            ADD COLUMN IF NOT EXISTS queries_affected INTEGER NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE erasure_log
            ADD COLUMN IF NOT EXISTS objects_failed INTEGER NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE erasure_log
            ADD COLUMN IF NOT EXISTS failed_storage_keys TEXT[]
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE erasure_log DROP COLUMN IF EXISTS failed_storage_keys")
    op.execute("ALTER TABLE erasure_log DROP COLUMN IF EXISTS objects_failed")
    op.execute("ALTER TABLE erasure_log DROP COLUMN IF EXISTS queries_affected")
