"""Complete evaluation execution and immutable dataset persistence."""

from __future__ import annotations

from alembic import op

revision = "0005_eval_execution"
down_revision = "0004_erasure_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE eval_datasets ADD COLUMN IF NOT EXISTS content_sha256 TEXT")
    op.execute(
        "ALTER TABLE eval_items ADD COLUMN IF NOT EXISTS external_id TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE eval_items ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'en'"
    )
    op.execute(
        "ALTER TABLE eval_items ADD COLUMN IF NOT EXISTS slice TEXT NOT NULL DEFAULT 'default'"
    )
    op.execute("ALTER TABLE eval_items ADD COLUMN IF NOT EXISTS must_exclude_chunk_ids UUID[]")
    op.execute("ALTER TABLE eval_items ADD COLUMN IF NOT EXISTS gold_chunk_labels TEXT[]")
    op.execute("ALTER TABLE eval_items ADD COLUMN IF NOT EXISTS must_exclude_chunk_labels TEXT[]")
    op.execute("ALTER TABLE eval_results ADD COLUMN IF NOT EXISTS citations JSONB")
    op.execute("ALTER TABLE cost_ledger ADD COLUMN IF NOT EXISTS eval_run_id UUID")
    op.execute("ALTER TABLE cost_ledger ADD COLUMN IF NOT EXISTS eval_item_id UUID")
    op.execute("ALTER TABLE cost_ledger ADD COLUMN IF NOT EXISTS reported_cost_usd NUMERIC(12, 6)")
    op.execute(
        "ALTER TABLE cost_ledger ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'succeeded'"
    )
    op.execute("ALTER TABLE cost_ledger ADD COLUMN IF NOT EXISTS error_detail TEXT")
    op.execute("UPDATE eval_items SET external_id = id::text WHERE external_id = ''")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cost_ledger__eval_run_id') THEN
                ALTER TABLE cost_ledger ADD CONSTRAINT fk_cost_ledger__eval_run_id
                    FOREIGN KEY (eval_run_id) REFERENCES eval_runs(id) ON DELETE SET NULL;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cost_ledger__eval_item_id') THEN
                ALTER TABLE cost_ledger ADD CONSTRAINT fk_cost_ledger__eval_item_id
                    FOREIGN KEY (eval_item_id) REFERENCES eval_items(id) ON DELETE SET NULL;
            END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_eval_items__dataset_external_id') THEN
                ALTER TABLE eval_items ADD CONSTRAINT uq_eval_items__dataset_external_id
                    UNIQUE (dataset_id, external_id);
            END IF;
        END $$
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cost_ledger__eval_run_item ON cost_ledger (eval_run_id, eval_item_id)"
    )
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_eval_results__run_item') THEN
                ALTER TABLE eval_results ADD CONSTRAINT uq_eval_results__run_item
                    UNIQUE (run_id, item_id);
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_index("ix_cost_ledger__eval_run_item", table_name="cost_ledger")
    op.drop_constraint("uq_eval_results__run_item", "eval_results", type_="unique")
    op.drop_constraint("uq_eval_items__dataset_external_id", "eval_items", type_="unique")
    op.drop_constraint("fk_cost_ledger__eval_item_id", "cost_ledger", type_="foreignkey")
    op.drop_constraint("fk_cost_ledger__eval_run_id", "cost_ledger", type_="foreignkey")
    for table, column in (
        ("cost_ledger", "error_detail"),
        ("cost_ledger", "status"),
        ("cost_ledger", "reported_cost_usd"),
        ("cost_ledger", "eval_item_id"),
        ("cost_ledger", "eval_run_id"),
        ("eval_items", "must_exclude_chunk_ids"),
        ("eval_items", "must_exclude_chunk_labels"),
        ("eval_items", "gold_chunk_labels"),
        ("eval_results", "citations"),
        ("eval_items", "language"),
        ("eval_items", "slice"),
        ("eval_items", "external_id"),
        ("eval_datasets", "content_sha256"),
    ):
        op.drop_column(table, column)
