from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class ModelSpec:
    model_id: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float


PRIMARY_MODEL = "claude-opus-5"
FALLBACK_MODEL = "claude-sonnet-5"
JUDGE_MODEL = "claude-haiku-4-5"


class ModelRegistry:
    """Canonical model IDs — never string-literal call sites."""

    _specs: ClassVar[dict[str, ModelSpec]] = {
        PRIMARY_MODEL: ModelSpec(PRIMARY_MODEL, 5.0, 25.0),
        FALLBACK_MODEL: ModelSpec(FALLBACK_MODEL, 3.0, 15.0),
        JUDGE_MODEL: ModelSpec(JUDGE_MODEL, 1.0, 5.0),
    }

    @classmethod
    def get(cls, model_id: str) -> ModelSpec:
        if model_id not in cls._specs:
            raise KeyError(f"Unknown model: {model_id}")
        return cls._specs[model_id]

    @classmethod
    def primary(cls) -> ModelSpec:
        return cls.get(PRIMARY_MODEL)

    @classmethod
    def judge(cls) -> ModelSpec:
        return cls.get(JUDGE_MODEL)

    @classmethod
    def fallback(cls) -> ModelSpec:
        return cls.get(FALLBACK_MODEL)
