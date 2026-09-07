# T-405 — Evaluation persistence and API foundation

| Field | Value |
| --- | --- |
| ID | T-405 |
| Phase | 4 — Evaluation |
| Status | in_progress |
| Branch | feat/T-405-eval-api |
| Depends on | T-402, T-403, T-404 |
| Blocks | T-406, T-407 |

## Goal

Expose tenant-scoped immutable evaluation datasets and asynchronous run records,
with paginated items/results and compatible run comparison.

## Acceptance criteria

- Admins can register and list datasets, inspect items, create runs, inspect status,
  page results, and compare runs from the same dataset.
- Dataset and run records are tenant scoped; duplicate dataset name/version returns
  a conflict; pagination follows existing keyset conventions.
- Run configuration, model identities, parameters, judge hash, and progress/error
  state are persisted. Worker execution derives tenant context from the run row.
- Worker failures/retries, result persistence, cost ledger rows, and API integration
  tests are complete before this task is marked done.

## Current implementation

The API foundation and contract tests are implemented. Worker execution and full
database integration remain pending and keep this task `in_progress`.

## Out of scope

Dashboard UI, strategy comparisons, CI gates, live model execution, and schema
rewrites of released migrations.

## Verification

Run Ruff, mypy, OpenAPI/type generation, API contract tests, and disposable Postgres
integration tests once worker execution is added.

## Rollback

Revert the API and contract changes. No migration has been added by the current
foundation work.
