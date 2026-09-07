from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from api.main import app
from api.routers.evals import DatasetCreate, EvalItemIn, _dataset_content_sha256


def test_evaluation_api_surface_is_registered() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/evals/datasets" in paths
    assert "/api/v1/evals/datasets/{dataset_id}/items" in paths
    assert "/api/v1/evals/runs" in paths
    assert "/api/v1/evals/runs/{run_id}/results" in paths
    assert "/api/v1/evals/runs/compare" in paths
    assert "/api/v1/evals/runs/{left_id}/compare/{right_id}" in paths


def test_dataset_registration_requires_items() -> None:
    with pytest.raises(ValidationError):
        DatasetCreate(name="smoke", version="1", items=[])


def test_dataset_item_accepts_historical_timezone() -> None:
    item = EvalItemIn(
        question="What changed?",
        expected_facts=["three days"],
        gold_chunk_ids=[uuid4()],
        as_of=datetime.fromisoformat("2025-01-01T00:00:00+00:00"),
    )
    assert item.as_of is not None and item.as_of.tzinfo is not None


def test_dataset_content_hash_ignores_resolved_symbolic_user_id() -> None:
    item = EvalItemIn(
        id="perm-001",
        slice="permission",
        question="What is the restricted reserve?",
        expected_answer_facts=["730 credits"],
        gold_chunk_ids=["acme-aster-restricted-v1"],
        language="en",
        acting_user="acme-viewer",
    )

    expected = "ce96c258362567ef27c1ea3d9a4e860f9c5fd99babc4484b12723702c930017d"
    assert _dataset_content_sha256([item]) == expected

    item.acting_user_id = uuid4()
    assert _dataset_content_sha256([item]) == expected
