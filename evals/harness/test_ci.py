from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from evals.harness.chunking import EXPERIMENT_VARIANTS
from evals.harness.ci import SMOKE_ITEMS_PER_SLICE, select_items
from evals.harness.compare import ComparisonConfig, config_dict, validate_config


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


def test_chunking_experiment__variants__are_explicit_and_serializable() -> None:
    assert EXPERIMENT_VARIANTS == ("fixed_token", "section_aware")
    config = ComparisonConfig(dataset_id=uuid4(), chunking_strategy=EXPERIMENT_VARIANTS[1])
    encoded = config_dict(config)
    assert encoded["chunking_strategy"] == "section_aware"
    decoded = validate_config(encoded)
    assert decoded.chunking_strategy == "section_aware"
