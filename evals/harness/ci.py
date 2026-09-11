"""Prepare and execute the inference-backed T-407 evaluation flow.

This command is intentionally small orchestration around the existing corpus
loader, evaluation API, worker, and T-406 comparison runner.  It does not have a
second retrieval implementation and it does not make paid model calls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

from evals.harness.compare import ComparisonConfig, config_dict, run_comparison

DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "evals" / "corpus.json"

SMOKE_ITEMS_PER_SLICE = 6
DATASET_NAME = "t407-ci-evaluation"
DATASET_VERSIONS = {"smoke": "smoke-v1", "full": "full-v1"}


def select_items(dataset_dir: Path, *, mode: str) -> list[dict[str, Any]]:
    """Return the full corpus or the stable six-per-slice PR subset."""
    from evals.harness.dataset import validate_dataset
    from evals.harness.metrics import load_dataset

    if mode not in DATASET_VERSIONS:
        raise ValueError(f"unsupported evaluation mode: {mode}")
    # Validate the committed 320-item artifact before selecting a subset.  This
    # prevents a green smoke run from silently masking a malformed full dataset.
    validate_dataset(dataset_dir, manifest_paths=(DEFAULT_MANIFEST,))
    items = [asdict(item) for item in load_dataset(dataset_dir)]
    if mode == "full":
        return items
    selected: list[dict[str, Any]] = []
    for slice_name in (
        "factual_pt",
        "factual_en",
        "crosslingual",
        "multi_hop",
        "versioned",
        "unanswerable",
        "permission",
        "injection",
    ):
        slice_items = [item for item in items if item["slice"] == slice_name]
        selected.extend(slice_items[:SMOKE_ITEMS_PER_SLICE])
    return selected


async def _load_eval_corpus() -> None:
    from db.session import get_session_factory, set_tenant_context
    from evals.harness.corpus import load_corpus, resolve_tenant_id

    factory = get_session_factory()
    async with factory() as session, session.begin():
        tenant_id = await resolve_tenant_id(session, "acme")
        await set_tenant_context(session, tenant_id)
        await load_corpus(session, manifest_path=DEFAULT_MANIFEST, tenant_id=tenant_id)


def _dataset_body(items: list[dict[str, Any]], *, mode: str) -> dict[str, Any]:
    return {
        "name": DATASET_NAME,
        "version": DATASET_VERSIONS[mode],
        "dataset_slice": "t407-smoke" if mode == "smoke" else "t407-full",
        "items": [
            {
                "id": item["id"],
                "slice": item["slice"],
                "question": item["question"],
                "expected_answer_facts": item["expected_answer_facts"],
                "gold_chunk_ids": item["gold_chunk_ids"],
                "must_exclude_chunk_ids": item.get("must_exclude_chunk_ids", []),
                "language": item["language"],
                "acting_user": item.get("acting_user"),
                "as_of": item.get("as_of"),
                "should_abstain": item["should_abstain"],
            }
            for item in items
        ],
    }


def _http_json(url: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    # Keep the only HTTP dependency in this command aligned with the comparison
    # runner, including its development-auth header and error handling.
    from evals.harness.compare import _http_json as request_json

    return request_json(url, method=method, body=body, user="acme-admin")


def run(mode: str, *, dataset_dir: Path, output: Path) -> None:
    items = select_items(dataset_dir, mode=mode)
    asyncio.run(_load_eval_corpus())

    import os

    api_url = os.environ.get("EVAL_API_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
    body = _dataset_body(items, mode=mode)
    dataset = _http_json(f"{api_url}/evals/datasets", method="POST", body=body)
    dataset_id = str(dataset["id"])
    config = ComparisonConfig(
        dataset_id=UUID(dataset_id),
        api_url=api_url,
        user="acme-admin",
        poll_interval_seconds=0.25,
        timeout_seconds=3600.0,
        bootstrap_resamples=1000 if mode == "smoke" else 10_000,
    )
    report = run_comparison(config)
    report["dataset"].update(
        {
            "name": body["name"],
            "version": body["version"],
            "dataset_slice": body["dataset_slice"],
            "content_sha256": dataset.get("content_sha256"),
        }
    )
    envelope = {
        "schema_version": 1,
        "metadata": {
            "task": "T-407",
            "mode": mode,
            "dataset": {
                "name": body["name"],
                "version": body["version"],
                "content_sha256": dataset.get("content_sha256"),
                "item_count": len(items),
                "item_ids": [item["id"] for item in items],
            },
            "config": config_dict(config),
        },
        "report": report,
    }
    output.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the T-407 CI evaluation flow")
    parser.add_argument("--mode", choices=tuple(DATASET_VERSIONS), default="smoke")
    parser.add_argument("--datasets", type=Path, default=Path("evals/datasets"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.mode, dataset_dir=args.datasets, output=args.output)


if __name__ == "__main__":
    main()
