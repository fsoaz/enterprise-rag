from __future__ import annotations

from pathlib import Path

from evals.harness.ci import SMOKE_ITEMS_PER_SLICE, select_items


def test_smoke_selection_is_stable_and_covers_every_slice() -> None:
    first = select_items(Path("evals/datasets"), mode="smoke")
    second = select_items(Path("evals/datasets"), mode="smoke")
    assert [item["id"] for item in first] == [item["id"] for item in second]
    assert len(first) == 8 * SMOKE_ITEMS_PER_SLICE
    assert {item["slice"] for item in first} == {
        "factual_pt",
        "factual_en",
        "crosslingual",
        "multi_hop",
        "versioned",
        "unanswerable",
        "permission",
        "injection",
    }
