"""Feedback uniqueness, injection-risk index, erasure support.

Revision ID: 0002_security_fixes
Revises: 0001_initial
Create Date: 2026-07-25

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_security_fixes"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One vote per user per query. Collapse any pre-existing duplicates to the most
    # recent vote first, otherwise the unique index cannot be built.
    op.execute(
        """
        DELETE FROM feedback f
         USING feedback newer
         WHERE f.query_id = newer.query_id
           AND f.user_id  = newer.user_id
           AND f.user_id IS NOT NULL
           AND (newer.created_at, newer.id) > (f.created_at, f.id)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_feedback__query_user
            ON feedback (query_id, user_id)
         WHERE user_id IS NOT NULL
        """
    )

    # Retrieval filters every query on injection_risk; without an index that is a
    # sequential scan on the hottest table in the system.
    op.execute(
        """
        CREATE INDEX ix_chunks__tenant_injection_risk
            ON chunks (tenant_id, injection_risk)
        """
    )

    # Erasure needs to find non-erased documents cheaply and, once erased, keep them
    # out of every retrieval path.
    op.execute(
        """
        CREATE INDEX ix_documents__tenant_erased
            ON documents (tenant_id)
         WHERE erased_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents__tenant_erased")
    op.execute("DROP INDEX IF EXISTS ix_chunks__tenant_injection_risk")
    op.execute("DROP INDEX IF EXISTS uq_feedback__query_user")
