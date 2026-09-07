# T-403 — Complete deterministic retrieval metrics

| Field | Value |
| --- | --- |
| ID | T-403 |
| Phase | 4 — Evaluation |
| Status | in_progress |
| Branch | feat/T-403-retrieval-metrics |
| Depends on | T-402 |
| Blocks | T-406, T-407 |

## Goal

Measure retrieval quality from the production retrieval path with complete
retrieval metrics, per-slice and per-language breakdowns, and version-aware gold
label handling.

## Acceptance criteria

- Recall, precision, nDCG, and MRR are computed at k=10 with duplicate retrieved
  versions removed before scoring.
- Aggregates are available overall, by slice, and by language; empty gold sets
  are handled explicitly rather than inflating quality.
- Dataset validation runs before retrieval; missing labels, users, versions, or
  incomplete items fail with an explicit error.
- Deterministic metric tests cover duplicate versions, multi-label gold, empty
  gold, ranking order, and per-group aggregation.
- Production `retrieve()` remains the measured path; no quality baseline or model
  identity is changed by this task.

## Out of scope

Answer judges, evaluation tables/API, strategy comparison, CI gates, live model
calls, and changing production retrieval defaults.

## Verification

Run Ruff, mypy, the focused metrics tests, and the full deterministic suite. Record
that real-model quality and latency remain unmeasured.

## Rollback

Revert this commit. No schema, migration, or production data changes.
