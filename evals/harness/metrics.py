from __future__ import annotations

import json
import math
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


def recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    if not gold:
        return 1.0 if not retrieved[:k] else 0.0
    top = set(retrieved[:k])
    return 1.0 if top.intersection(gold) else 0.0


def mrr_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    if not gold:
        return 1.0 if not retrieved[:k] else 0.0
    gold_set = set(gold)
    for i, cid in enumerate(retrieved[:k]):
        if cid in gold_set:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    if not gold:
        return 1.0 if not retrieved[:k] else 0.0
    gold_set = set(gold)
    dcg = 0.0
    for i, cid in enumerate(retrieved[:k]):
        if cid in gold_set:
            dcg += 1.0 / math.log2(i + 2)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return dcg / ideal if ideal else 0.0


def precision_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    """Precision over the returned top-k, with explicit empty-gold semantics."""
    top = retrieved[:k]
    if not top:
        return 1.0 if not gold else 0.0
    return sum(item in set(gold) for item in top) / len(top)


def deduplicate_retrieved(retrieved: list[str]) -> list[str]:
    """Collapse repeated chunks from one document version, preserving rank."""
    return list(dict.fromkeys(retrieved))


def aggregate_retrieval_metrics(
    rows: list[tuple[list[str], list[str]]],
) -> dict[str, float]:
    if not rows:
        return {"recall@10": 0.0, "precision@10": 0.0, "nDCG@10": 0.0, "MRR@10": 0.0}
    return {
        "recall@10": sum(recall_at_k(r, g, 10) for r, g in rows) / len(rows),
        "precision@10": sum(precision_at_k(r, g, 10) for r, g in rows) / len(rows),
        "nDCG@10": sum(ndcg_at_k(r, g, 10) for r, g in rows) / len(rows),
        "MRR@10": sum(mrr_at_k(r, g, 10) for r, g in rows) / len(rows),
    }


def aggregate_grouped_metrics(
    rows: list[tuple[str, str, list[str], list[str]]],
) -> dict[str, dict[str, float]]:
    """Return metrics grouped by ``(slice, language)``."""
    grouped: dict[tuple[str, str], list[tuple[list[str], list[str]]]] = {}
    for slice_name, language, retrieved, gold in rows:
        grouped.setdefault((slice_name, language), []).append((retrieved, gold))
    return {
        f"{slice_name}:{language}": aggregate_retrieval_metrics(group)
        for (slice_name, language), group in sorted(grouped.items())
    }
