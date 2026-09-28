# T-412 — Correct developer documentation against the implementation

| Field | Value |
| --- | --- |
| **ID** | `T-412` |
| **Phase** | `4 — Evaluation` (documentation debt found on the Phase 4 stack) |
| **Status** | `done` (local; not yet committed) |
| **Branch** | `docs/T-412-documentation-accuracy-audit` |
| **Size** | `M` |
| **Depends on** | `T-411` (`78c5ead`) |
| **Blocks** | none |

## Goal

Every developer-facing document states what the code does today, marks designed-but-unbuilt
behavior as proposed, and routes each fact to one canonical source.

## Context

A documentation audit (AUDIT → EDIT, user-requested) compared `README.md`, `AGENTS.md`,
`docs/guides/`, `docs/standards/`, and `docs/context/` with the Makefile, Compose file,
workflows, `.importlinter`, `openapi.json`, and source. Verdict: **NEEDS REVISION**. Setup
commands, ports, seeded identities, and anchors were correct; the architecture and API
rules described large parts of the design as current, and several status statements
contradicted [current_task.md](../execution/current_task.md).

User decisions: keep architecture design intent but label each section
Implemented / Partial / Proposed; track the work as its own task and branch.

## Acceptance Criteria

- [x] No edited document states that an unimplemented mechanism exists; unbuilt design is labelled Proposed.
- [x] `api_rules.md` status codes, fields, routes, SSE events, and rate-limit headers match `openapi.json` and the routers.
- [x] README and roadmap status lines agree with `current_task.md`.
- [ ] Local-development guide commands run as written against the documented environment (evaluation commands load `.env`; readiness wait loops). [VERIFY] Consistent with the Makefile, Compose file, CI workflow, and scripts, and `bash -n` clean, but not executed: `uv` and Docker were unavailable.
- [x] Import-boundary statements match `.importlinter`, including the api→worker exception and `packages/evaluation`.
- [x] All relative links and anchors in edited documents resolve; all `bash` blocks pass `bash -n`.
- [x] Code defects found during the audit are logged in [review_notes.md](../execution/review_notes.md), not fixed here.

## Out of Scope

- Application code, tests, generated OpenAPI and TypeScript types.
- Renaming tests to the documented naming convention.
- Resolving product or milestone-assignment decisions (reported only).
- Historical task files and execution records other than this task's bookkeeping.

## Design Notes

Canonical sources: live status → `current_task.md`; routes and schemas → `openapi.json`;
setup detail and troubleshooting → `docs/guides/local-development.md`; coding rules →
`conventions.md`; environment variables → `.env.example`. ADR bodies are historical and
are not rewritten.

## Files Expected to Change

| Path | Change |
| --- | --- |
| `README.md`, `AGENTS.md` | Status, prerequisites, boundaries, duplication removal |
| `docs/guides/local-development.md` | Command fixes, ports, troubleshooting |
| `docs/standards/*.md` | Accuracy corrections |
| `docs/context/*.md` | Status labels and accuracy corrections |
| `.env.example` | Document `BIND_ADDR`, `MAX_UPLOAD_BYTES` |
| `docs/execution/*` | Review notes, work log, evidence |

## Test Plan

| Tier | What is covered |
| --- | --- |
| Unit | n/a: documentation only |
| Integration | n/a |
| Contract | `make openapi-check` still passes (no API file changes) |
| Security | n/a: does not touch security surface; security claims corrected to match code |
| Eval | n/a |
| E2E | n/a |

**Commands to run:**

```text
make openapi-check
git diff --check
# plus a relative-link/anchor resolver and bash -n over fenced bash blocks (E-017)
```

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| A correction is itself wrong | Medium | Each correction cites the file it was checked against; spot-checked claims only |
| Links into renamed headings break | Medium | Anchor checker across the whole `docs/` tree and README |

## Rollback

Documentation only: no migration and no data change. Revert the commit.

---

## Completion Record

- **Completed:** `2026-09-27`
- **PR:** not opened
- **Evidence:** [test_evidence.md](../execution/test_evidence.md) entry `E-017`
- **Work log:** [work_log.md](../execution/work_log.md) entry `2026-09-27`
- **Deviations from plan:** `.env.example` also documents `BIND_ADDR`; `apps/web/README.md` links were repointed after README anchors moved. Commands in the guide are checked for consistency and syntax, not executed (no `uv` or Docker in the environment).
- **Follow-ups raised:** R-125 – R-134
