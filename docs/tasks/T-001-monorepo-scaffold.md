# T-001 — Monorepo scaffold

| Field | Value |
| --- | --- |
| **ID** | `T-001` |
| **Phase** | `0` |
| **Status** | `done` |
| **Branch** | `chore/T-001-monorepo-scaffold` |
| **Size** | `M` |
| **Depends on** | none |
| **Blocks** | `T-002`, `T-005` |

---

## Goal

The repository has a runnable monorepo layout with lint/typecheck tooling and stub services so later Phase 0 tasks can land Compose, migrations, and auth without inventing structure.

## Context

- Design: [architecture.md § 16](../context/architecture.md#16-repository-layout)
- Conventions: [conventions.md](../standards/conventions.md)
- Stories satisfied: none directly (enables PA-1)
- Prior findings: none

## Acceptance Criteria

- [x] Layout matches architecture § 16: `apps/{api,worker,inference,web}`, `packages/{domain,db,retrieval,llm,observability}`, `evals/`, `infra/compose/`, `tests/`
- [x] `uv` workspace installs; `ruff check` and `ruff format --check` pass
- [x] `mypy` runs on `packages/` (strict) and apps without errors
- [x] `import-linter` contracts pass
- [x] `apps/api` exposes `/health` and `/ready`
- [x] `apps/worker` has a no-op Celery task importable
- [x] `apps/inference` exposes stub `POST /v1/embed` and `POST /v1/rerank` returning 1024-dim vectors
- [x] `apps/web` is a Next.js App Router project; `tsc --noEmit` and `biome check` pass
- [x] `make lint` and `make typecheck` succeed

## Out of Scope

- Docker Compose services (T-002)
- Alembic migrations / RLS (T-003)
- OIDC auth (T-004)
- CI workflows (T-005)
- Seed data (T-006)
- Real BGE models

## Design Notes

- Workspace root `pyproject.toml` with uv workspace members for apps and packages.
- Inference stubs return deterministic zero vectors so callers can wire HTTP without GPU weights.
- Web scaffold is minimal (no shadcn yet) — enough for typecheck; UI polish lands in Phase 6a.

## Files Expected to Change

| Path | Change |
| --- | --- |
| `apps/*` | New service stubs |
| `packages/*` | New package skeletons |
| `pyproject.toml`, `Makefile`, configs | Tooling |
| `docs/execution/current_task.md` | Status |
| `docs/tasks/T-001-*.md` | This file |

## New Dependencies

| Package | Why | Why not stdlib / existing | Licence | Last release |
| --- | --- | --- | --- | --- |
| fastapi | API framework per architecture | stdlib has no ASGI app framework | MIT | current |
| uvicorn | ASGI server | needed to run FastAPI | BSD | current |
| celery | Async jobs per architecture | stdlib has no distributed task queue | BSD | current |
| pydantic / pydantic-settings | Settings + schemas | required by FastAPI stack | MIT | current |
| httpx | HTTP client for tests/clients | urllib insufficient for async | BSD | current |
| pytest | Test runner per conventions | — | MIT | current |
| ruff / mypy / import-linter | Lint/types/boundaries | per conventions | MIT | current |
| next / react / typescript | Web UI per architecture | — | MIT | current |
| @biomejs/biome | TS lint/format | replaces eslint/prettier | MIT | current |

## Test Plan

| Tier | What is covered |
| --- | --- |
| Unit | Health endpoints return 200; embed returns dim 1024 |
| Integration | n/a |
| Contract | n/a |
| Security | n/a: does not touch security surface |
| Eval | n/a |
| E2E | n/a |

**Commands to run:**

```text
make lint
make typecheck
uv run pytest apps/api/tests apps/inference/tests -q
```

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Python 3.14 local vs 3.12 target | medium | Pin `.python-version` to 3.12; uv manages toolchain |
| Next.js scaffold version drift | low | Pin Next 15 App Router |

## Rollback

Revert the commit; no migrations or data.

---

## Completion Record

- **Completed:** 2026-07-25
- **PR:** —
- **Evidence:** —
- **Work log:** —
- **Deviations from plan:** —
- **Follow-ups raised:** —
