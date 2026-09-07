# T-403 — Complete deterministic retrieval metrics

| Field | Value |
| --- | --- |
| ID | T-403 |
| Phase | 4 — Evaluation |
| Status | done |
| Branch | feat/T-403-retrieval-metrics |
| Depends on | T-402 |
| Blocks | T-407 |

## Goal

Measure retrieval quality from the production retrieval path with complete
retrieval metrics, per-slice and per-language breakdowns, and version-aware gold
label handling.

## Acceptance criteria

- [x] Recall, precision, nDCG, and MRR are computed at k=10 with duplicate retrieved
  versions removed before scoring.
- [x] Aggregates are available overall, by slice, and by language; empty gold sets
  are handled explicitly rather than inflating quality.
- [x] Dataset validation runs before retrieval; missing labels, users, versions, or
  incomplete items fail with an explicit error.
- [x] Deterministic metric tests cover duplicate versions, multi-label gold, empty
  gold, ranking order, and per-group aggregation.
- [x] Production `retrieve()` remains the measured path; no quality baseline or model
  identity is changed by this task.

## Out of scope

Answer judges, evaluation tables/API, strategy comparison, CI gates, live model
calls, and changing production retrieval defaults.

## Verification

Focused metrics/dataset tests, Ruff, mypy, and the production-path evaluation
worker checks pass. Real-model quality and latency remain unmeasured.

## Rollback

Revert this commit. No schema, migration, or production data changes.
