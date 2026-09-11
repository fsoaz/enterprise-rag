"""Configurable evaluation strategy comparisons.

The comparison core is deliberately independent of the API and Celery clients.  It
can therefore be unit-tested with plain dictionaries while the command line runner
uses the existing ``POST /evals/runs`` worker path.  Reports are built from persisted
``EvalResult`` observations, never from a second retrieval implementation.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from domain.types import ChunkingStrategy

DEFAULT_STRATEGIES = ("hybrid_rrf", "dense_only", "lexical_only", "hybrid_rerank")
VALID_STRATEGIES = frozenset(DEFAULT_STRATEGIES)
DEFAULT_BOOTSTRAP_RESAMPLES = 10_000
DEFAULT_BOOTSTRAP_SEED = 406
TERMINAL_STATUSES = frozenset({"complete", "incomplete", "failed"})


class ComparisonConfigError(ValueError):
    """Raised when a comparison configuration is invalid or ambiguous."""


class ComparisonError(RuntimeError):
    """Raised when a comparison cannot produce a complete report."""


@dataclass(frozen=True, slots=True)
class ComparisonConfig:
    dataset_id: UUID
    strategies: tuple[str, ...] = DEFAULT_STRATEGIES
    embedding_models: tuple[dict[str, Any], ...] = ({"name": "BAAI/bge-m3", "version": "stub-v0"},)
    rerankers: tuple[dict[str, Any] | None, ...] = (
        {"name": "identity-rerank-test-stub", "version": "stub-v0"},
    )
    retrieval_params: tuple[dict[str, Any], ...] = ({},)
    baseline: str = "hybrid_rrf"
    api_url: str = "http://localhost:8000/api/v1"
    user: str = "acme-admin"
    generator_model: str = "extractive-fallback"
    poll_interval_seconds: float = 1.0
    timeout_seconds: float = 3600.0
    bootstrap_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED
    chunking_strategy: str | None = None


@dataclass(frozen=True, slots=True)
class RunSpec:
    strategy: str
    embedding_model: dict[str, Any]
    reranker: dict[str, Any] | None
    retrieval_params: dict[str, Any]


def _strict_dict(value: Any, *, field: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ComparisonConfigError(f"{field} must be an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ComparisonConfigError(f"{field} contains unknown fields: {unknown}")
    return dict(value)


def _nonempty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ComparisonConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _positive_number(value: Any, *, field: str, integer: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ComparisonConfigError(f"{field} must be positive")
    if integer and not isinstance(value, int):
        raise ComparisonConfigError(f"{field} must be an integer")
    return value


def _model_config(value: Any, *, field: str, allow_none: bool = False) -> dict[str, Any] | None:
    if value is None and allow_none:
        return None
    raw = _strict_dict(
        value,
        field=field,
        allowed={"name", "version", "endpoint"},
    )
    name = _nonempty_string(raw.get("name"), field=f"{field}.name")
    version = _nonempty_string(raw.get("version"), field=f"{field}.version")
    endpoint = raw.get("endpoint")
    if endpoint is not None:
        endpoint = _nonempty_string(endpoint, field=f"{field}.endpoint").rstrip("/")
    return {"name": name, "version": version, **({"endpoint": endpoint} if endpoint else {})}


def validate_config(raw: Mapping[str, Any]) -> ComparisonConfig:
    """Validate a JSON configuration with strict, deterministic semantics."""
    if not isinstance(raw, Mapping):
        raise ComparisonConfigError("comparison configuration must be an object")
    allowed = {
        "dataset_id",
        "strategies",
        "embedding_models",
        "rerankers",
        "retrieval_params",
        "baseline",
        "api_url",
        "user",
        "generator_model",
        "poll_interval_seconds",
        "timeout_seconds",
        "bootstrap_resamples",
        "bootstrap_seed",
        "chunking_strategy",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ComparisonConfigError(f"configuration contains unknown fields: {unknown}")
    try:
        dataset_id = UUID(str(raw["dataset_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ComparisonConfigError("dataset_id must be a UUID") from exc

    strategies_value = raw.get("strategies", list(DEFAULT_STRATEGIES))
    if not isinstance(strategies_value, list) or not strategies_value:
        raise ComparisonConfigError("strategies must be a non-empty array")
    strategies = tuple(_nonempty_string(value, field="strategies[]") for value in strategies_value)
    invalid = sorted(set(strategies) - VALID_STRATEGIES)
    if invalid:
        raise ComparisonConfigError(f"unsupported strategies: {invalid}")
    if len(set(strategies)) != len(strategies):
        raise ComparisonConfigError("strategies must not contain duplicates")

    embeddings_value = raw.get(
        "embedding_models",
        [{"name": "BAAI/bge-m3", "version": "stub-v0"}],
    )
    if not isinstance(embeddings_value, list) or not embeddings_value:
        raise ComparisonConfigError("embedding_models must be a non-empty array")
    embeddings_list: list[dict[str, Any]] = []
    for index, value in enumerate(embeddings_value):
        model = _model_config(value, field=f"embedding_models[{index}]")
        assert model is not None
        embeddings_list.append(model)
    rerankers_value = raw.get(
        "rerankers",
        [{"name": "identity-rerank-test-stub", "version": "stub-v0"}],
    )
    if not isinstance(rerankers_value, list) or not rerankers_value:
        raise ComparisonConfigError("rerankers must be a non-empty array")
    normalized_rerankers: list[dict[str, Any] | None] = []
    for index, value in enumerate(rerankers_value):
        normalized_rerankers.append(
            _model_config(value, field=f"rerankers[{index}]") if value is not None else None
        )

    params_value = raw.get("retrieval_params", [{}])
    if not isinstance(params_value, list) or not params_value:
        raise ComparisonConfigError("retrieval_params must be a non-empty array")
    retrieval_params: list[dict[str, Any]] = []
    for index, value in enumerate(params_value):
        params = _strict_dict(
            value,
            field=f"retrieval_params[{index}]",
            allowed={"top_k", "retrieval_k", "rrf_k"},
        )
        for key in params:
            params[key] = _positive_number(
                params[key], field=f"retrieval_params[{index}].{key}", integer=True
            )
        retrieval_params.append(params)

    baseline = _nonempty_string(raw.get("baseline", "hybrid_rrf"), field="baseline")
    if baseline not in strategies:
        raise ComparisonConfigError("baseline must be one of strategies")
    api_url = _nonempty_string(
        raw.get("api_url", "http://localhost:8000/api/v1"), field="api_url"
    ).rstrip("/")
    user = _nonempty_string(raw.get("user", "acme-admin"), field="user")
    generator_model = _nonempty_string(
        raw.get("generator_model", "extractive-fallback"), field="generator_model"
    )
    poll_interval = float(
        _positive_number(
            raw.get("poll_interval_seconds", 1.0),
            field="poll_interval_seconds",
        )
    )
    timeout = float(_positive_number(raw.get("timeout_seconds", 3600.0), field="timeout_seconds"))
    resamples_value = _positive_number(
        raw.get("bootstrap_resamples", DEFAULT_BOOTSTRAP_RESAMPLES),
        field="bootstrap_resamples",
        integer=True,
    )
    assert isinstance(resamples_value, int)
    resamples = resamples_value
    seed = raw.get("bootstrap_seed", DEFAULT_BOOTSTRAP_SEED)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ComparisonConfigError("bootstrap_seed must be an integer")
    if resamples < 100:
        raise ComparisonConfigError("bootstrap_resamples must be at least 100")
    chunking_strategy = raw.get("chunking_strategy")
    if chunking_strategy is not None:
        chunking_strategy = _nonempty_string(chunking_strategy, field="chunking_strategy")
        if chunking_strategy not in {strategy.value for strategy in ChunkingStrategy}:
            raise ComparisonConfigError(f"unsupported chunking_strategy: {chunking_strategy}")
    return ComparisonConfig(
        dataset_id=dataset_id,
        strategies=strategies,
        embedding_models=tuple(embeddings_list),
        rerankers=tuple(normalized_rerankers),
        retrieval_params=tuple(retrieval_params),
        baseline=baseline,
        api_url=api_url,
        user=user,
        generator_model=generator_model,
        poll_interval_seconds=poll_interval,
        timeout_seconds=timeout,
        bootstrap_resamples=resamples,
        bootstrap_seed=seed,
        chunking_strategy=chunking_strategy,
    )


def load_config(path: str | Path) -> ComparisonConfig:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComparisonConfigError(f"could not load JSON configuration {source}: {exc}") from exc
    return validate_config(raw)


def config_dict(config: ComparisonConfig) -> dict[str, Any]:
    result = {
        "dataset_id": str(config.dataset_id),
        "strategies": list(config.strategies),
        "embedding_models": [dict(model) for model in config.embedding_models],
        "rerankers": [dict(model) if model is not None else None for model in config.rerankers],
        "retrieval_params": [dict(params) for params in config.retrieval_params],
        "baseline": config.baseline,
        "api_url": config.api_url,
        "user": config.user,
        "generator_model": config.generator_model,
        "poll_interval_seconds": config.poll_interval_seconds,
        "timeout_seconds": config.timeout_seconds,
        "bootstrap_resamples": config.bootstrap_resamples,
        "bootstrap_seed": config.bootstrap_seed,
    }
    if config.chunking_strategy is not None:
        result["chunking_strategy"] = config.chunking_strategy
    return result


def expand_sweep(config: ComparisonConfig) -> list[RunSpec]:
    """Return a stable Cartesian product, with the configured baseline first."""
    specs: list[RunSpec] = []
    seen: set[str] = set()
    for strategy in config.strategies:
        for embedding in config.embedding_models:
            for reranker in config.rerankers:
                for params in config.retrieval_params:
                    spec = RunSpec(
                        strategy,
                        dict(embedding),
                        dict(reranker) if reranker else None,
                        dict(params),
                    )
                    key = json.dumps(
                        {
                            "strategy": spec.strategy,
                            "embedding_model": spec.embedding_model,
                            "reranker": spec.reranker,
                            "retrieval_params": spec.retrieval_params,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if key in seen:
                        raise ComparisonConfigError(f"duplicate sweep combination: {key}")
                    seen.add(key)
                    specs.append(spec)
    specs.sort(key=lambda spec: (spec.strategy != config.baseline,))
    return specs


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


def _http_json(
    url: str, *, method: str = "GET", body: dict[str, Any] | None = None, user: str
) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "X-Dev-User": user},
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError) as exc:
        detail = exc.read().decode() if isinstance(exc, HTTPError) else str(exc)
        raise ComparisonError(f"comparison API request failed: {method} {url}: {detail}") from exc


def run_comparison(config: ComparisonConfig) -> dict[str, Any]:
    """Execute the sweep sequentially through the existing API/Celery path."""
    specs = expand_sweep(config)
    run_ids: list[str] = []
    run_rows: list[dict[str, Any]] = []
    deadline = time.monotonic() + config.timeout_seconds
    for spec in specs:
        embedding = spec.embedding_model
        reranker = spec.reranker
        params = {
            "comparison": config_dict(config),
            "embedding_model_name": embedding["name"],
            "embedding_model_version": embedding["version"],
            "inference_endpoint": embedding.get("endpoint") or None,
            "reranker_identity": reranker["name"] if reranker else None,
            "reranker_version": reranker.get("version") if reranker else None,
            "reranker_endpoint": reranker.get("endpoint") if reranker else None,
            "retrieval": dict(spec.retrieval_params),
        }
        if config.chunking_strategy is not None:
            params["chunking_strategy"] = config.chunking_strategy
        payload = {
            "dataset_id": str(config.dataset_id),
            "strategy": spec.strategy,
            "embedding_model": embedding["name"],
            "reranker": reranker["name"] if reranker else None,
            "generator_model": config.generator_model,
            "params": params,
        }
        row = _http_json(
            f"{config.api_url}/evals/runs", method="POST", body=payload, user=config.user
        )
        run_id = str(row["id"])
        run_ids.append(run_id)
        lookup_deadline = time.monotonic() + min(30.0, config.timeout_seconds)
        while True:
            try:
                current = _http_json(f"{config.api_url}/evals/runs/{run_id}", user=config.user)
            except ComparisonError as exc:
                # The API commits the run and publishes the Celery task in adjacent
                # transactions. A worker or read replica can briefly race the
                # status lookup; tolerate that narrow eventual-consistency window,
                # but do not turn a permanently missing run into an hour-long poll.
                if "HTTP Error 404" not in str(exc) or time.monotonic() >= lookup_deadline:
                    raise
                time.sleep(config.poll_interval_seconds)
                continue
            status = str(current.get("status", "queued"))
            if status in TERMINAL_STATUSES:
                run_rows.append(current)
                break
            if time.monotonic() >= deadline:
                raise ComparisonError(f"run {run_id} did not become terminal before timeout")
            time.sleep(config.poll_interval_seconds)
    result_rows: dict[str, list[dict[str, Any]]] = {}
    for run_id in run_ids:
        result_cursor: str | None = None
        rows: list[dict[str, Any]] = []
        while True:
            query = {"limit": "200"}
            if result_cursor:
                query["cursor"] = result_cursor
            page = _http_json(
                f"{config.api_url}/evals/runs/{run_id}/results?{urlencode(query)}", user=config.user
            )
            rows.extend(page.get("data", []))
            result_cursor = page.get("next_cursor")
            if not result_cursor:
                break
        result_rows[run_id] = rows
    items: list[dict[str, Any]] = []
    item_cursor: str | None = None
    while True:
        query = {"limit": "200"}
        if item_cursor:
            query["cursor"] = item_cursor
        items_page = _http_json(
            f"{config.api_url}/evals/datasets/{config.dataset_id}/items?{urlencode(query)}",
            user=config.user,
        )
        items.extend(items_page.get("data", []))
        item_cursor = items_page.get("next_cursor")
        if not item_cursor:
            break
    report = build_report(
        run_rows,
        items,
        result_rows,
        baseline_id=run_ids[0],
        bootstrap_resamples=config.bootstrap_resamples,
        bootstrap_seed=config.bootstrap_seed,
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a deterministic retrieval strategy comparison"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_comparison(load_config(args.config))
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
