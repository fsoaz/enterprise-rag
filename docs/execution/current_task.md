# Current Task

> Exactly one task is `in_progress` at a time. Update this file when you start and when you finish.
> **Related:** [../tasks/README.md](../tasks/README.md) · [work_log.md](./work_log.md) · [../context/roadmap.md](../context/roadmap.md)

---

## Active

| Field | Value |
| --- | --- |
| **Task** | `T-001` — Monorepo scaffold |
| **File** | `docs/tasks/T-001-monorepo-scaffold.md` *(not yet created)* |
| **Phase** | 0 — Foundation |
| **Status** | `planned` |
| **Branch** | — |
| **Started** | — |
| **Blockers** | None |

### Next step

Planning is complete. To begin implementation:

1. Copy [../tasks/TEMPLATE.md](../tasks/TEMPLATE.md) to `docs/tasks/T-001-monorepo-scaffold.md` and fill it in.
2. Create branch `chore/T-001-monorepo-scaffold`.
3. Set the status above to `in_progress` and record the start date.

### Notes

The repository currently contains documentation only. No code, no dependencies, no containers. Phase 0 exists to prove tenancy and auth before any feature is built on top of them — in particular the RLS backstop test in [testing.md § 6.1](../standards/testing.md#61-tenant-isolation), which is the single most important test in Phase 0.

---

## Up Next

Phase 0 remainder, in order. See [roadmap.md § Phase 0](../context/roadmap.md#phase-0--foundation).

| ID | Title | Depends on |
| --- | --- | --- |
| `T-002` | Docker Compose stack (Postgres+pgvector, Redis, MinIO, Keycloak) | `T-001` |
| `T-003` | Initial migrations + RLS policies | `T-002` |
| `T-004` | OIDC auth, tenant context, `SET LOCAL app.current_tenant` | `T-003` |
| `T-005` | CI pipeline | `T-001` |
| `T-006` | Seed two demo tenants with distinct users and groups | `T-004` |

---

## Recently Completed

| Date | Task | Summary |
| --- | --- | --- |
| 2026-07-25 | — | Planning phase: `docs/` populated. See [work_log.md](./work_log.md). |
