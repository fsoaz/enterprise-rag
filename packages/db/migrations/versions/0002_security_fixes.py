"""Feedback uniqueness, injection-risk index, erasure support.

Revision ID: 0002_security_fixes
Revises: 0001_initial
Create Date: 2026-07-25

.. warning::

   ``0001_initial`` builds the schema with ``Base.metadata.create_all()``, so it is
   **not immutable** — it re-derives the schema from the current models on every run.
   A model-level change therefore alters what an already-released migration does, and
   a fresh database ends up with objects that a previously-migrated database lacks.

   Consequence for any future migration: never assume a model-defined object is absent
   just because no migration created it. Guard model-derived DDL with ``IF NOT EXISTS``
   and always test ``upgrade head`` from an **empty** database, not only from your dev
   database's current revision. Round-tripping up → down → up on an already-migrated
   database does not exercise this path, which is how it reached CI.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_security_fixes"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every CREATE here is IF NOT EXISTS, because 0001_initial builds the schema with
    # `Base.metadata.create_all()` rather than explicit DDL. That makes 0001 a moving
    # target: it reflects whatever the models look like *now*, so adding an Index to a
    # model's __table_args__ retroactively changes what 0001 creates.
    #
    # uq_feedback__query_user is exactly that case. It lives on the Feedback model, so
    # a database built from empty gets it from 0001, while one already stamped at 0001
    # from before the model changed does not. Both states must upgrade cleanly.
    # See the note in the module docstring — this is a property of 0001, not of this
    # migration, and every future model-level index will hit it.

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
        CREATE UNIQUE INDEX IF NOT EXISTS uq_feedback__query_user
            ON feedback (query_id, user_id)
         WHERE user_id IS NOT NULL
        """
    )

    # Retrieval filters every query on injection_risk; without an index that is a
    # sequential scan on the hottest table in the system. Not on the model, so this
    # migration genuinely owns it.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chunks__tenant_injection_risk
            ON chunks (tenant_id, injection_risk)
        """
    )

    # Erasure needs to find non-erased documents cheaply and, once erased, keep them
    # out of every retrieval path.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_documents__tenant_erased
            ON documents (tenant_id)
         WHERE erased_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents__tenant_erased")
    op.execute("DROP INDEX IF EXISTS ix_chunks__tenant_injection_risk")
    op.execute("DROP INDEX IF EXISTS uq_feedback__query_user")
