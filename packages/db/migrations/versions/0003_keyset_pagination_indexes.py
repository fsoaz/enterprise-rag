"""Composite indexes for stable keyset pagination.

Revision ID: 0003_keyset_pagination_indexes
Revises: 0002_security_fixes
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_keyset_pagination_indexes"
down_revision: str | None = "0002_security_fixes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS is mandatory here because 0001 derives its fresh schema from
    # current model metadata; see the warning in 0002_security_fixes.
    statements = (
        """
        CREATE INDEX IF NOT EXISTS ix_collections__tenant_created_id
            ON collections (tenant_id, created_at DESC, id DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_documents__tenant_created_id
            ON documents (tenant_id, created_at DESC, id DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_acl_entries__tenant_created_id
            ON acl_entries (tenant_id, created_at DESC, id DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_erasure_log__tenant_created_id
            ON erasure_log (tenant_id, created_at DESC, id DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_document_versions__document_created_id
            ON document_versions (document_id, created_at DESC, id DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_ingestion_jobs__version_created_id
            ON ingestion_jobs (document_version_id, created_at DESC, id DESC)
        """,
    )
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    for name in (
        "ix_ingestion_jobs__version_created_id",
        "ix_document_versions__document_created_id",
        "ix_erasure_log__tenant_created_id",
        "ix_acl_entries__tenant_created_id",
        "ix_documents__tenant_created_id",
        "ix_collections__tenant_created_id",
    ):
        op.execute(f"DROP INDEX IF EXISTS {name}")
