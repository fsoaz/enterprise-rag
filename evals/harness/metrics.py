"""Golden dataset loading for the offline harness.

Ranking metrics live in ``evaluation.metrics`` because the evaluation worker computes
them at run time; this module keeps only the committed-file reader (ADR-016).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class EvalItem:
    id: str
    slice: str
    question: str
    gold_chunk_ids: list[str]
    should_abstain: bool
    expected_answer_facts: list[str]
    language: str = "en"
    acting_user: str | None = None
    as_of: str | None = None
    must_exclude_chunk_ids: list[str] = field(default_factory=list)


def load_dataset(path: Path) -> list[EvalItem]:
    items: list[EvalItem] = []
    for file in sorted(path.glob("*.jsonl")):
        slice_name = file.stem
        for line in file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw: dict[str, Any] = json.loads(line)
            items.append(
                EvalItem(
                    id=str(raw["id"]),
                    slice=slice_name,
                    question=str(raw["question"]),
                    gold_chunk_ids=[str(x) for x in raw.get("gold_chunk_ids", [])],
                    should_abstain=bool(raw.get("should_abstain", False)),
                    expected_answer_facts=[str(x) for x in raw.get("expected_answer_facts", [])],
                    language=str(raw.get("language", "en")),
                    acting_user=(
                        str(raw["acting_user"]) if raw.get("acting_user") is not None else None
                    ),
                    as_of=str(raw["as_of"]) if raw.get("as_of") is not None else None,
                    must_exclude_chunk_ids=[str(x) for x in raw.get("must_exclude_chunk_ids", [])],
                )
            )
    return items
