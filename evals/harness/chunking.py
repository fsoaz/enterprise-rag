"""Compare production-path chunking variants for T-408 / Q-1.

Each variant reloads the same synthetic corpus into the same disposable tenant,
then runs the existing T-406 sweep. Evaluation source labels are resolved by
version at run time, so replacing chunks between sweeps does not alter the
immutable dataset or its content hash.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from domain.types import (
    DEFAULT_CHUNKING_STRATEGY,
    ChunkingStrategy,
)
from evals.harness.ci import _dataset_body, _http_json, select_items
from evals.harness.compare import ComparisonConfig, config_dict, run_comparison

DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "evals" / "corpus.json"

EXPERIMENT_DATASET_NAME = "t408-chunking-experiment"
EXPERIMENT_DATASET_VERSIONS = {"smoke": "smoke-v1", "full": "full-v1"}
EXPERIMENT_VARIANTS = (ChunkingStrategy.FIXED_TOKEN.value, ChunkingStrategy.SECTION_AWARE.value)


async def _load_eval_corpus(chunking_strategy: str) -> None:
    from db.session import get_session_factory, set_tenant_context
    from evals.harness.corpus import load_corpus, resolve_tenant_id

    factory = get_session_factory()
    async with factory() as session, session.begin():
        tenant_id = await resolve_tenant_id(session, "acme")
        await set_tenant_context(session, tenant_id)
        await load_corpus(
            session,
            manifest_path=DEFAULT_MANIFEST,
            tenant_id=tenant_id,
            chunking_strategy=chunking_strategy,
        )


def _dataset_body_for_experiment(items: list[dict[str, Any]], *, mode: str) -> dict[str, Any]:
    body = _dataset_body(items, mode=mode)
    body["name"] = EXPERIMENT_DATASET_NAME
    body["version"] = EXPERIMENT_DATASET_VERSIONS[mode]
    body["dataset_slice"] = f"t408-{mode}"
    return body


def _config(dataset_id: UUID, *, mode: str, chunking_strategy: str) -> ComparisonConfig:
    return ComparisonConfig(
        dataset_id=dataset_id,
        api_url=os.environ.get("EVAL_API_URL", "http://127.0.0.1:8000/api/v1").rstrip("/"),
        user="acme-admin",
        poll_interval_seconds=0.25,
        timeout_seconds=3600.0,
        bootstrap_resamples=1000 if mode == "smoke" else 10_000,
        chunking_strategy=chunking_strategy,
    )


async def _run(mode: str, *, dataset_dir: Path, output: Path) -> None:
    if mode not in EXPERIMENT_DATASET_VERSIONS:
        raise ValueError(f"unsupported evaluation mode: {mode}")
    items = select_items(dataset_dir, mode=mode)

    # The first load also establishes the version IDs used when registering the
    # dataset's symbolic gold-source labels.
    await _load_eval_corpus(DEFAULT_CHUNKING_STRATEGY)
    api_url = os.environ.get("EVAL_API_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
    body = _dataset_body_for_experiment(items, mode=mode)
    dataset = _http_json(f"{api_url}/evals/datasets", method="POST", body=body)
    dataset_id = UUID(str(dataset["id"]))

    reports: dict[str, dict[str, Any]] = {}
    for index, variant in enumerate(EXPERIMENT_VARIANTS):
        if index:
            await _load_eval_corpus(variant)
        config = _config(dataset_id, mode=mode, chunking_strategy=variant)
        report = run_comparison(config)
        report["dataset"].update(
            {
                "name": body["name"],
                "version": body["version"],
                "dataset_slice": body["dataset_slice"],
                "content_sha256": dataset.get("content_sha256"),
            }
        )
        reports[variant] = {
            "config": config_dict(config),
            "report": report,
        }

    envelope = {
        "schema_version": 1,
        "metadata": {
            "task": "T-408",
            "question": "Q-1",
            "mode": mode,
            "dataset": {
                "name": body["name"],
                "version": body["version"],
                "content_sha256": dataset.get("content_sha256"),
                "item_count": len(items),
                "item_ids": [item["id"] for item in items],
            },
            "variants": list(EXPERIMENT_VARIANTS),
        },
        "variants": reports,
    }
    output.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(mode: str, *, dataset_dir: Path, output: Path) -> None:
    asyncio.run(_run(mode, dataset_dir=dataset_dir, output=output))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the T-408 chunking experiment")
    parser.add_argument("--mode", choices=tuple(EXPERIMENT_DATASET_VERSIONS), default="smoke")
    parser.add_argument("--datasets", type=Path, default=Path("evals/datasets"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.mode, dataset_dir=args.datasets, output=args.output)


if __name__ == "__main__":
    main()
