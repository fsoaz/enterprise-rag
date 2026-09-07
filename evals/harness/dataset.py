"""Validation for immutable golden evaluation items."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from domain.temporal import parse_as_of
from evals.harness.manifest import CorpusError, read_manifest

SLICES = (
    "factual_pt",
    "factual_en",
    "crosslingual",
    "multi_hop",
    "versioned",
    "unanswerable",
    "permission",
    "injection",
)


def validate_dataset(
    dataset_dir: Path, *, manifest_paths: tuple[Path, ...]
) -> list[dict[str, Any]]:
    """Read and validate every item, returning a stable flattened representation."""
    labels: set[str] = set()
    for manifest_path in manifest_paths:
        labels.update(
            version["label"]
            for document in read_manifest(
                manifest_path, fixture_dir=manifest_path.parent / "fixtures"
            )["documents"]
            for version in document["versions"]
        )
    all_items: list[dict[str, Any]] = []
    ids: set[str] = set()
    for slice_name in SLICES:
        path = dataset_dir / f"{slice_name}.jsonl"
        if not path.is_file():
            raise CorpusError(f"missing dataset slice {slice_name}")
        items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        if len(items) != 40:
            raise CorpusError(f"slice {slice_name} has {len(items)} items; expected 40")
        for item in items:
            required = {
                "id",
                "question",
                "gold_chunk_ids",
                "expected_answer_facts",
                "should_abstain",
                "language",
            }
            if (
                set(item) - required - {"as_of", "acting_user", "must_exclude_chunk_ids"}
                or not required <= item.keys()
            ):
                raise CorpusError(f"item {item.get('id', '<missing>')} has invalid fields")
            if not item["id"] or item["id"] in ids or not item["question"].strip():
                raise CorpusError(f"duplicate or empty item {item.get('id', '<missing>')}")
            ids.add(item["id"])
            if item["language"] not in {"pt", "en"}:
                raise CorpusError(f"item {item['id']} has unsupported language")
            for label in [*item["gold_chunk_ids"], *item.get("must_exclude_chunk_ids", [])]:
                if label not in labels and not label.startswith("chunk-"):
                    raise CorpusError(f"item {item['id']} references unknown source {label}")
            if item.get("as_of") is not None:
                parse_as_of(item["as_of"])
            if item["gold_chunk_ids"] and not item["expected_answer_facts"]:
                raise CorpusError(f"supported item {item['id']} has no expected facts")
            if item["should_abstain"] and item["gold_chunk_ids"]:
                raise CorpusError(f"abstaining item {item['id']} has gold sources")
            all_items.append({**item, "slice": slice_name})
    if sum(item["language"] == "pt" for item in all_items if item["slice"] == "factual_pt") != 40:
        raise CorpusError("factual_pt is not Portuguese")
    if sum(item["language"] == "en" for item in all_items if item["slice"] == "factual_en") != 40:
        raise CorpusError("factual_en is not English")
    crosslingual = [item for item in all_items if item["slice"] == "crosslingual"]
    if sum(item["language"] == "pt" for item in crosslingual) != 20:
        raise CorpusError("crosslingual PT direction is incomplete")
    if sum(item["language"] == "en" for item in crosslingual) != 20:
        raise CorpusError("crosslingual EN direction is incomplete")
    versioned = [item for item in all_items if item["slice"] == "versioned"]
    if not any(item.get("as_of") == "2024-06-01" for item in versioned):
        raise CorpusError("versioned slice lacks an old-version case")
    if not any(item.get("as_of") == "2025-01-01" for item in versioned):
        raise CorpusError("versioned slice lacks a boundary case")
    if not any("as_of" not in item for item in versioned):
        raise CorpusError("versioned slice lacks a current-version case")
    if not any(item.get("as_of") == "2023-01-01" and item["should_abstain"] for item in versioned):
        raise CorpusError("versioned slice lacks an absent-version case")
    permission = [item for item in all_items if item["slice"] == "permission"]
    if {item.get("acting_user") for item in permission} != {"acme-viewer", "acme-member"}:
        raise CorpusError("permission slice lacks both acting users")
    injection = [item for item in all_items if item["slice"] == "injection"]
    if not all(item.get("must_exclude_chunk_ids") for item in injection):
        raise CorpusError("injection slice lacks prohibited-source labels")
    return all_items
