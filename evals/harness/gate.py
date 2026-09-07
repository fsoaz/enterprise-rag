"""Deterministic CI regression gates for evaluation comparison reports.

The gate compares the configured baseline strategy in a current comparison report
with the same strategy in a committed, known-good report.  It deliberately does
not compare randomly generated run IDs, and it fails closed when the dataset,
model identity, or required metric set is incompatible.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class GateError(ValueError):
    """Raised when a report cannot be safely evaluated against its baseline."""


class RegressionDetected(GateError):
    """Raised when one or more configured regression thresholds are exceeded."""


THRESHOLDS: dict[str, tuple[str, float]] = {
    "recall@10": ("minimum", 0.02),
    "nDCG@10": ("minimum", 0.02),
    "faithfulness": ("minimum", 0.02),
    "citation_precision": ("minimum", 0.02),
    "unsupported_answer_rate": ("maximum", 0.01),
    "correct_abstention_rate": ("minimum", 0.03),
}

# These metrics are counts/rates of prohibited events.  Any non-zero value fails,
# even when it is smaller than a quality threshold.
ZERO_TOLERANCE_METRICS = ("tenant_leakage", "acl_bypass")
BASELINE_STRATEGY = "hybrid_rrf"
BASELINE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class GateViolation:
    metric: str
    message: str
    current: float | None = None
    baseline: float | None = None
    limit: float | None = None


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    violations: tuple[GateViolation, ...]
    checked_metrics: tuple[str, ...]
    strategy: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "strategy": self.strategy,
            "checked_metrics": list(self.checked_metrics),
            "violations": [
                {
                    "metric": violation.metric,
                    "message": violation.message,
                    "current": violation.current,
                    "baseline": violation.baseline,
                    "limit": violation.limit,
                }
                for violation in self.violations
            ],
        }


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GateError(f"{field} must be an object")
    return value


def _report_and_metadata(
    value: Mapping[str, Any], *, field: str
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    report_value = value.get("report", value)
    report = _mapping(report_value, field=f"{field}.report")
    metadata_value = value.get("metadata", {})
    metadata = _mapping(metadata_value, field=f"{field}.metadata")
    return report, metadata


def _run_for_strategy(report: Mapping[str, Any], strategy: str, *, field: str) -> str:
    runs = report.get("runs")
    if not isinstance(runs, list):
        raise GateError(f"{field}.runs must be an array")
    matches = [
        str(run["id"])
        for run in runs
        if isinstance(run, Mapping) and str(run.get("strategy")) == strategy and run.get("id")
    ]
    if len(matches) != 1:
        raise GateError(f"{field} must contain exactly one run for strategy {strategy!r}")
    return matches[0]


def _metric_value(report: Mapping[str, Any], metric: str, run_id: str, *, field: str) -> float:
    overall = _mapping(report.get("overall"), field=f"{field}.overall")
    metric_rows = _mapping(overall.get(metric), field=f"{field}.overall.{metric}")
    row = _mapping(metric_rows.get(run_id), field=f"{field}.overall.{metric}.{run_id}")
    value = row.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GateError(f"{field} is missing numeric metric {metric!r}")
    return float(value)


def _compatible(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> list[GateViolation]:
    violations: list[GateViolation] = []
    current_report, current_meta = _report_and_metadata(current, field="current")
    baseline_report, baseline_meta = _report_and_metadata(baseline, field="baseline")

    current_dataset = _mapping(
        current_meta.get("dataset", current_report.get("dataset")), field="current.dataset"
    )
    baseline_dataset = _mapping(
        baseline_meta.get("dataset", baseline_report.get("dataset")), field="baseline.dataset"
    )
    for key in ("name", "version", "content_sha256", "item_count", "item_ids"):
        if (key in current_dataset or key in baseline_dataset) and current_dataset.get(
            key
        ) != baseline_dataset.get(key):
            violations.append(
                GateViolation(
                    "compatibility",
                    f"dataset.{key} differs between current and committed baseline",
                )
            )

    current_config = _mapping(current_meta.get("config", {}), field="current.config")
    baseline_config = _mapping(baseline_meta.get("config", {}), field="baseline.config")
    for key in ("strategies", "baseline", "embedding_models", "rerankers", "retrieval_params"):
        if (key in current_config or key in baseline_config) and current_config.get(
            key
        ) != baseline_config.get(key):
            violations.append(
                GateViolation(
                    "compatibility",
                    f"config.{key} differs between current and committed baseline",
                )
            )
    return violations


def evaluate_gate(
    current: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    strategy: str = BASELINE_STRATEGY,
) -> GateResult:
    """Evaluate a current report against a compatible committed baseline.

    The returned result is also serializable for CI artifacts.  ``GateError`` is
    used for malformed/incompatible reports; ``RegressionDetected`` is reserved
    for a well-formed report that violates a quality or security threshold.
    """
    compatibility = _compatible(current, baseline)
    if compatibility:
        raise GateError("incompatible baseline: " + "; ".join(v.message for v in compatibility))

    current_report, _ = _report_and_metadata(current, field="current")
    baseline_report, _ = _report_and_metadata(baseline, field="baseline")
    current_run = _run_for_strategy(current_report, strategy, field="current")
    baseline_run = _run_for_strategy(baseline_report, strategy, field="baseline")

    violations: list[GateViolation] = []
    checked: list[str] = []
    for metric, (direction, allowance) in THRESHOLDS.items():
        current_value = _metric_value(current_report, metric, current_run, field="current")
        baseline_value = _metric_value(baseline_report, metric, baseline_run, field="baseline")
        checked.append(metric)
        delta = current_value - baseline_value
        failed = delta < -allowance if direction == "minimum" else delta > allowance
        if failed:
            comparison = "drop" if direction == "minimum" else "increase"
            violations.append(
                GateViolation(
                    metric,
                    f"{metric} {comparison} {abs(delta):.4f} exceeds {allowance:.4f}",
                    current_value,
                    baseline_value,
                    allowance,
                )
            )

    # Security is checked for every configured run, not only the baseline.  A
    # strategy that looks good on average must never hide one leaking result.
    run_ids = [
        str(run["id"])
        for run in current_report.get("runs", [])
        if isinstance(run, Mapping) and run.get("id")
    ]
    for metric in ZERO_TOLERANCE_METRICS:
        for run_id in run_ids:
            value = _metric_value(current_report, metric, run_id, field="current")
            checked.append(f"{metric}:{run_id}")
            if value != 0.0:
                violations.append(
                    GateViolation(
                        metric,
                        f"{metric} is non-zero for run {run_id}: {value:.4f}",
                        value,
                        0.0,
                        0.0,
                    )
                )
        baseline_run_ids = [
            str(run["id"])
            for run in baseline_report.get("runs", [])
            if isinstance(run, Mapping) and run.get("id")
        ]
        for run_id in baseline_run_ids:
            baseline_value = _metric_value(baseline_report, metric, run_id, field="baseline")
            if baseline_value != 0.0:
                raise GateError(f"committed baseline has non-zero {metric} for run {run_id}")

    result = GateResult(not violations, tuple(violations), tuple(checked), strategy)
    if violations:
        raise RegressionDetected(json.dumps(result.as_dict(), sort_keys=True))
    return result


def load_baseline(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"could not load baseline {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError("baseline must be a JSON object")
    if value.get("schema_version") not in (None, BASELINE_SCHEMA_VERSION):
        raise GateError(f"unsupported baseline schema version: {value.get('schema_version')}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate an eval report against a CI baseline")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    current = load_baseline(args.report)
    baseline = load_baseline(args.baseline)
    try:
        result = evaluate_gate(current, baseline)
    except RegressionDetected as exc:
        if args.output:
            args.output.write_text(str(exc) + "\n", encoding="utf-8")
        raise SystemExit(f"evaluation regression detected: {exc}") from exc
    except GateError as exc:
        raise SystemExit(f"evaluation gate could not run: {exc}") from exc
    encoded = json.dumps(result.as_dict(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
