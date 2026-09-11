"""Deterministic comparison reports over persisted evaluation results.

Reports are built from persisted ``EvalResult`` observations, never from a second
retrieval implementation. The API comparison endpoint and the offline sweep runner in
``evals.harness.compare`` share this core, so it depends on neither client and can be
unit-tested with plain dictionaries.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import Any

DEFAULT_BOOTSTRAP_RESAMPLES = 10_000
DEFAULT_BOOTSTRAP_SEED = 406


class ComparisonError(RuntimeError):
    """Raised when a comparison cannot produce a complete report."""


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires observations")
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def paired_bootstrap_ci(
    differences: Sequence[float],
    *,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> tuple[float, float] | None:
    """Return a deterministic percentile 95% CI for paired differences."""
    if not differences:
        return None
    values = [float(value) for value in differences]
    rng = random.Random(seed)
    estimates = [
        fmean(values[rng.randrange(len(values))] for _ in range(len(values)))
        for _ in range(resamples)
    ]
    return _percentile(estimates, 0.025), _percentile(estimates, 0.975)


def _object_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _run_status(run: Any) -> str:
    params = _object_value(run, "params", {}) or {}
    status = params.get("status") if isinstance(params, Mapping) else None
    if status:
        return str(status)
    return "complete" if _object_value(run, "finished_at") is not None else "queued"


def _metric_value(result: Any, metric: str) -> float | None:
    metrics = _object_value(result, "metrics", {}) or {}
    value = metrics.get(metric) if isinstance(metrics, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _run_metadata(run: Any) -> dict[str, Any]:
    fields = ("id", "dataset_id", "strategy", "embedding_model", "reranker", "generator_model")
    metadata = {
        field: str(_object_value(run, field))
        if field.endswith("_id") or field == "id"
        else _object_value(run, field)
        for field in fields
    }
    metadata["status"] = _run_status(run)
    metadata["params"] = dict(_object_value(run, "params", {}) or {})
    return metadata


def _metric_matrix(
    run_ids: list[str],
    baseline_id: str,
    item_ids: list[str],
    result_by_run: dict[str, dict[str, Any]],
    *,
    resamples: int,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metric_names = sorted(
        {
            name
            for run_results in result_by_run.values()
            for result in run_results.values()
            for name, value in (_object_value(result, "metrics", {}) or {}).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    )
    values_by_run: dict[str, dict[str, float | None]] = {}
    for run_id in run_ids:
        values_by_run[run_id] = {
            metric: (
                fmean(observations)
                if (
                    observations := [
                        value
                        for item_id in item_ids
                        if (value := _metric_value(result_by_run[run_id][item_id], metric))
                        is not None
                    ]
                )
                else None
            )
            for metric in metric_names
        }
    matrix: dict[str, Any] = {}
    baseline_results = result_by_run[baseline_id]
    for metric in metric_names:
        matrix[metric] = {}
        baseline_observations = {
            item_id: _metric_value(baseline_results[item_id], metric) for item_id in item_ids
        }
        for run_id in run_ids:
            value = values_by_run[run_id][metric]
            baseline_value = values_by_run[baseline_id][metric]
            delta = None if value is None or baseline_value is None else value - baseline_value
            interval: tuple[float, float] | None = None
            significant: bool | None = None
            if run_id == baseline_id:
                delta = 0.0 if value is not None else None
            else:
                paired: list[float] = []
                for item_id in item_ids:
                    base = baseline_observations[item_id]
                    candidate = _metric_value(result_by_run[run_id][item_id], metric)
                    if base is not None and candidate is not None:
                        paired.append(candidate - base)
                interval = paired_bootstrap_ci(paired, resamples=resamples, seed=seed)
                significant = None if interval is None else interval[0] > 0 or interval[1] < 0
            matrix[metric][run_id] = {
                "value": value,
                "delta": delta,
                "absolute_delta": abs(delta) if delta is not None else None,
                "ci_lower": interval[0] if interval else None,
                "ci_upper": interval[1] if interval else None,
                "confidence_interval": (
                    {"lower": interval[0], "upper": interval[1]} if interval else None
                ),
                "significant": significant,
            }
    return matrix, values_by_run


def build_report(
    runs: Sequence[Any],
    items: Sequence[Any],
    results_by_run: Mapping[str, Sequence[Any]],
    *,
    baseline_id: str | None = None,
    bootstrap_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Build and validate the canonical deterministic comparison report."""
    if not runs:
        raise ComparisonError("comparison requires at least one run")
    run_ids = [str(_object_value(run, "id")) for run in runs]
    selected_baseline = baseline_id or run_ids[0]
    if selected_baseline not in run_ids:
        raise ComparisonError(f"baseline run is not in comparison: {selected_baseline}")
    dataset_ids = {str(_object_value(run, "dataset_id")) for run in runs}
    if len(dataset_ids) != 1:
        raise ComparisonError("runs use incompatible datasets")
    item_ids = [str(_object_value(item, "id")) for item in items]
    expected = set(item_ids)
    if len(expected) != len(item_ids):
        raise ComparisonError("dataset contains duplicate item ids")
    result_maps: dict[str, dict[str, Any]] = {}
    incomplete: list[str] = []
    missing: dict[str, list[str]] = {}
    extra: dict[str, list[str]] = {}
    for run, run_id in zip(runs, run_ids, strict=True):
        if _run_status(run) != "complete":
            incomplete.append(run_id)
        rows = list(results_by_run.get(run_id, ()))
        mapping = {str(_object_value(row, "item_id")): row for row in rows}
        duplicate_count = len(rows) != len(mapping)
        missing_ids = sorted(expected - mapping.keys())
        extra_ids = sorted(mapping.keys() - expected)
        if missing_ids or extra_ids or duplicate_count:
            missing[run_id] = missing_ids
            extra[run_id] = extra_ids
            if duplicate_count:
                extra[run_id].append("<duplicate-item-id>")
        result_maps[run_id] = mapping
    if incomplete or missing:
        details = []
        if incomplete:
            details.append(f"incomplete runs: {', '.join(incomplete)}")
        if missing:
            details.append("missing or duplicate results: " + ", ".join(sorted(missing)))
        raise ComparisonError("; ".join(details))

    slices: dict[str, list[str]] = {}
    for item, item_id in zip(items, item_ids, strict=True):
        slice_name = str(
            _object_value(item, "slice", None)
            or _object_value(item, "item_slice", None)
            or _object_value(item, "dataset_slice", None)
            or "default"
        )
        slices.setdefault(slice_name, []).append(item_id)
    all_matrix, _ = _metric_matrix(
        run_ids,
        selected_baseline,
        item_ids,
        result_maps,
        resamples=bootstrap_resamples,
        seed=bootstrap_seed,
    )
    by_slice: dict[str, Any] = {}
    coverage: dict[str, Any] = {}
    for slice_name, slice_item_ids in sorted(slices.items()):
        matrix, _ = _metric_matrix(
            run_ids,
            selected_baseline,
            slice_item_ids,
            result_maps,
            resamples=bootstrap_resamples,
            seed=bootstrap_seed,
        )
        by_slice[slice_name] = matrix
        coverage[slice_name] = {
            run_id: {
                "expected_items": len(slice_item_ids),
                "result_count": len(slice_item_ids),
                "item_ids": slice_item_ids,
            }
            for run_id in run_ids
        }
    return {
        "baseline_run_id": selected_baseline,
        "runs": [_run_metadata(run) for run in runs],
        "dataset": {
            "id": str(_object_value(runs[0], "dataset_id")),
            "compatible": len(dataset_ids) == 1,
            "item_count": len(item_ids),
        },
        "overall": all_matrix,
        "by_slice": by_slice,
        "coverage": {
            "overall": {
                run_id: {
                    "expected_items": len(item_ids),
                    "result_count": len(result_maps[run_id]),
                    "item_ids": item_ids,
                }
                for run_id in run_ids
            },
            "by_slice": coverage,
        },
        "statistics": {
            "method": "paired_bootstrap_percentile",
            "resamples": bootstrap_resamples,
            "seed": bootstrap_seed,
            "confidence": 0.95,
        },
    }
