"""Evaluation source-label bindings, resolved from the database instead of fixture files.

Revision ID: 0006_eval_source_labels
Revises: 0005_eval_execution
Create Date: 2026-09-11

``0001_initial`` builds the schema with ``Base.metadata.create_all()``, so on a database
migrated from empty this table already exists when this revision runs — without row-level
security, because 0001's RLS loop names its tables explicitly. Every statement here is
therefore idempotent, and RLS is applied unconditionally (R-058, ADR-016).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_eval_source_labels"
down_revision: str | None = "0005_eval_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_source_labels (
            tenant_id UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            document_version_id UUID NOT NULL
                REFERENCES document_versions (id) ON DELETE CASCADE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT pk_eval_source_labels PRIMARY KEY (tenant_id, label)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eval_source_labels__document_version_id
            ON eval_source_labels (document_version_id)
        """
    )
    op.execute("ALTER TABLE eval_source_labels ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE eval_source_labels FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON eval_source_labels")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON eval_source_labels
          FOR ALL
          USING (tenant_id = current_setting('app.current_tenant')::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON eval_source_labels TO rag_app")
    op.execute("GRANT SELECT ON eval_source_labels TO rag_maint")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS eval_source_labels")
