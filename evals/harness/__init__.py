"""Offline evaluation harness for Milestone A.

Scores the real retrieval pipeline against the fixture corpus in ``evals/fixtures``.
Requires a migrated + seeded database and a reachable inference service.

    uv run python -m evals.harness.run --load-corpus   # ingest fixtures, then score
    uv run python -m evals.harness.run --strategy hybrid_rrf
"""

from __future__ import annotations
