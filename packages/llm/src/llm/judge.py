"""Versioned entailment rubric loading and conservative response parsing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_LINE = re.compile(
    r"^\s*(?P<index>\d+)\s*[.):\-]?\s*"
    r"(?P<label>entailed|partial|contradicted|unrelated)\s*$",
    re.IGNORECASE,
)
_LABELS = frozenset({"entailed", "partial", "contradicted", "unrelated"})


def rubric_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "evals" / "harness" / "judges" / "entailment_v1.md"
        if candidate.is_file():
            return candidate
    raise RuntimeError("versioned entailment rubric is missing")


def rubric_text() -> str:
    return rubric_path().read_text(encoding="utf-8")


def rubric_hash() -> str:
    return hashlib.sha256(rubric_text().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ParsedJudgement:
    labels: list[str]
    complete: bool
    error: str | None = None


def parse_judgement(text: str, pair_count: int) -> ParsedJudgement:
    labels = ["unrelated"] * pair_count
    seen: set[int] = set()
    invalid = False
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _LINE.match(line)
        if match is None:
            invalid = True
            continue
        index = int(match.group("index"))
        label = match.group("label").lower()
        if index < 0 or index >= pair_count or index in seen or label not in _LABELS:
            invalid = True
            continue
        labels[index] = label
        seen.add(index)
    complete = not invalid and len(seen) == pair_count
    return ParsedJudgement(
        labels=labels,
        complete=complete,
        error=None
        if complete
        else "judge response did not contain exactly one valid label per pair",
    )
