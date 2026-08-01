# T-005 — CI pipeline

| Field | Value |
| --- | --- |
| **ID** | `T-005` |
| **Phase** | `0` |
| **Status** | `done` |
| **Branch** | `chore/T-005-ci-pipeline` |
| **Size** | `S` |
| **Depends on** | `T-001` |
| **Blocks** | merge gates for later phases |

---

## Goal

Every PR and push to `main` runs lint, typecheck, unit tests, and a Postgres-backed migration/RLS job so tenancy and toolchain regressions cannot merge quietly.

## Context

- Roadmap: [roadmap.md § Phase 0](../context/roadmap.md#phase-0--foundation)
- Testing: [testing.md](../standards/testing.md)
- Stories satisfied: PA-1 (tooling)
- Prior findings: none

## Acceptance Criteria

- [x] Workflow on `pull_request` and `push` to `main`
- [x] Lint job: `ruff` + `biome`
- [x] Typecheck job: `mypy` + `import-linter` + `tsc`
- [x] Unit job: `pytest -m "not integration"`
- [x] Integration-db job: Postgres service, `init.sql`, alembic upgrade/downgrade/upgrade, seed, RLS + auth tests
- [x] Python 3.12, Node 22, `uv`

## Out of Scope

- Deploy / CD
- Eval smoke gates (Phase 4)
- Playwright e2e

## Design Notes

- Jobs are parallel where possible; integration-db is the only job that needs the pgvector service.
- Roles/extensions come from `infra/compose/postgres/init.sql` before Alembic.

## Files Expected to Change

| Path | Change |
| --- | --- |
| `.github/workflows/ci.yml` | New |

## Test Plan

| Tier | What is covered |
| --- | --- |
| CI | Workflow parses; jobs mirror `make lint` / `make typecheck` / `make test` |

**Commands to run:**

```text
# Local equivalents
make lint
make typecheck
uv run pytest -q -m "not integration"
```

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Service container init race | Low | pg_isready healthcheck + apt psql step |

## Rollback

Revert the workflow file.

---

## Completion Record

- **Completed:** `2026-07-25`
- **PR:** pending
- **Evidence:** local lint/typecheck/pytest
- **Work log:** pending
- **Deviations from plan:** none
- **Follow-ups raised:** none
