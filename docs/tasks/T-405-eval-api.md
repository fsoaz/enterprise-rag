# T-405 — Evaluation persistence and API

| Field | Value |
| --- | --- |
| ID | T-405 |
| Phase | 4 — Evaluation |
| Status | done |
| Branch | feat/T-405-eval-api |
| Depends on | T-402, T-403, T-404 |
| Blocks | T-407 |

## Goal

Expose tenant-scoped immutable evaluation datasets and asynchronous run records,
with paginated items/results and compatible run comparison.

## Acceptance criteria

- [x] Admins can register and list datasets, inspect items, create runs, inspect status,
  page results, and compare runs from the same dataset.
- [x] Dataset and run records are tenant scoped; duplicate dataset name/version returns
  a conflict; pagination follows existing keyset conventions.
- [x] Run configuration, model identities, parameters, judge hash, and progress/error
  state are persisted. Worker execution derives tenant context from the run row.
- [x] Worker failures/retries, result persistence, cost ledger rows, and API integration
  tests are complete before this task is marked done.

## Current implementation

The API and worker now persist immutable dataset identity, production-path
generation and versioned Haiku judging results, citations, quality, abstention,
and authorization metrics. Results are idempotent across task redelivery and
item failures remain explicit in the run. Disposable-Postgres integration
evidence is complete: the full integration marker passed against Podman-managed
Postgres, Redis, and stub inference after a fresh migration and seed.

## Out of scope

Dashboard UI, strategy comparisons, CI gates, live model execution, and schema
rewrites of released migrations.

## Verification

Focused worker/API/judge tests, Ruff, mypy, OpenAPI/type generation, offline
migration SQL generation, and the disposable Postgres integration suite pass.

## Rollback

Revert the API, worker, contract, model, and additive `0005_eval_execution`
migration changes. No production database was modified by this implementation.
