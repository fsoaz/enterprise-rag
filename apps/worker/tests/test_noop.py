from __future__ import annotations

from worker.tasks.noop import noop


def test_noop_task() -> None:
    result = noop()
    assert result == {"status": "ok"}
