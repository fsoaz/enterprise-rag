"""Initial schema: all Milestone A tables, RLS, and grants.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-25

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

import db.models  # noqa: F401
from db.base import Base

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that carry tenant_id and must have RLS (architecture § 4.2).
TENANT_SCOPED_TABLES: tuple[str, ...] = (
    "users",
    "groups",
    "user_groups",
    "roles",
    "collections",
    "documents",
    "document_versions",
    "chunks",
    "chunk_embeddings",
    "acl_entries",
    "acl_versions",
    "queries",
    "query_citations",
    "feedback",
    "ingestion_jobs",
    "cost_ledger",
    "erasure_log",
    "eval_datasets",
    "eval_items",
    "eval_runs",
    "eval_results",
)

# Global / root tables — no RLS.
GLOBAL_TABLES: tuple[str, ...] = (
    "tenants",
    "model_prices",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    for table in TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
              FOR ALL
              USING (tenant_id = current_setting('app.current_tenant')::uuid)
              WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)
            """
        )

    # Explicit grants (also covered by default privileges from init.sql).
    all_tables = ", ".join((*GLOBAL_TABLES, *TENANT_SCOPED_TABLES))
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {all_tables} TO rag_app")
    op.execute(f"GRANT SELECT ON {all_tables} TO rag_maint")
    # Maint may enumerate tenants and pending jobs; mutations stay on rag_app.
    op.execute("GRANT SELECT ON tenants, ingestion_jobs TO rag_maint")


def downgrade() -> None:
    for table in TENANT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
