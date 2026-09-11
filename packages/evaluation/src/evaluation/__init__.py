"""Evaluation runtime shared by the API and worker.

Offline tooling, fixtures, and datasets live in the repository's ``evals/`` directory.
That directory imports this package; product code never imports ``evals`` (ADR-016).
"""

from __future__ import annotations
