# T-411 — Bound evaluation complexity after T-410

| Field | Value |
| --- | --- |
| **ID** | `T-411` |
| **Phase** | `4 — Evaluation` |
| **Status** | `done` |
| **Branch** | `refactor/T-411-bounded-complexity-cleanup` |
| **Size** | `M` |
| **Depends on** | `T-410` (`b6e68c1`) |
| **Blocks** | none |

## Goal

Committed runs are visible before dispatch, comparison has one contract, advertised
configuration controls behavior, and deterministic CI accurately describes its coverage.

## Context

User-requested follow-up addressing C11, C10, C13, and C8 in that order.
T-410 was committed separately before this work. See
[architecture § 11](../context/architecture.md#11-evaluation-architecture) and
[testing guidance](../standards/testing.md). Supports PA-4.
The dispatch ordering defect is verified from code; it is not a conclusive
explanation of the historical E-014 failures.

## Acceptance Criteria

- [x] C11: commit queued runs before publication; commit publication failures in a
  second transaction while retaining HTTP 202. A separate tenant-scoped connection
  can see the run during dispatch. Commit failure prevents dispatch.
- [x] Harness 404 errors fail immediately; normal status polling and timeout remain.
- [x] C10: only the canonical comparison matrix endpoint remains, with completeness,
  validation, authorization, and tenant isolation covered; generated contracts match.
- [x] C13: remove unused Settings/environment configuration and propagation for
  LLM_PRIMARY_MODEL, LLM_JUDGE_MODEL, LLM_FALLBACK_MODEL, API_HOST, API_PORT,
  EMBEDDING_DIM, RERANKER_MODEL_NAME, and DATABASE_URL_SYNC. Preserve used Python
  dimension constants, inference settings, and private environment files.
- [x] C8: gate recall@10 and nDCG@10 with existing 0.02 allowances; tenant leakage
  and ACL bypass remain zero-tolerance for every run. Four answer metrics remain
  computed/reported but have no thresholds and are absent from checked_metrics.
- [x] Baselines, dataset hashes, compatibility checks, labels, rubric, retry policy,
  idempotency, and security boundaries are preserved.
- [x] Lint, type checks, unit/integration tests, generated contracts, deterministic
  API/Celery smoke comparison, and built-image imports/rubric are verified locally.

## Out of Scope

No migration, re-baselining, paid model run, gate-profile framework, or architecture
replacement. Retry classification, sweep dimensions, cost accounting, database roles,
ACL surfaces, ingest fallback, package paths, and chunking variants remain deferred.
Live-model quality and hosted CI evidence remain unmeasured by local verification.

## Design Notes

Use the request session's explicit commit and existing transaction-local tenant
context reapplication. Keep the evaluation API, Celery worker, and comparison report.
Model selection comes from the existing LLM registry; startup commands bind the
server; the vector dimension is fixed at 1024.

## Files Expected to Change

| Path | Change |
| --- | --- |
| `apps/api/` | Dispatch ordering, legacy route deletion, configuration, tests |
| `evals/harness/` | Polling and deterministic gate cleanup, focused tests |
| `.env.example`, `infra/compose/`, `.github/workflows/`, `scripts/` | Remove unused configuration |
| OpenAPI documents and generated frontend types | Regenerate through repository commands |
| `docs/` | Task, current guidance, local evidence, work log |

## Test Plan

| Tier | Coverage |
| --- | --- |
| Unit | Commit failure, polling/404/timeout, retrieval/security gates, degraded answers |
| Integration | Dispatch visibility and persisted failure; comparison authorization and completeness |
| Contract | `make openapi openapi-check`; frontend API type generation |
| Security | Existing tenant/ACL tests, fresh tenant-scoped failure lookup |
| Eval | Deterministic smoke against unchanged t407-smoke baseline |
| E2E | API/Celery runs; built image imports and rubric hash |

Commands: `make lint typecheck`, `make test`, `make test-integration`,
`make openapi openapi-check`, `npm run generate:api-types --prefix apps/web`,
`python -m evals.harness.ci --mode smoke`, `python -m evals.harness.gate`,
API image build and Python import/rubric check. Use disposable Podman equivalents
where host tooling or Compose is unavailable, and record exact evidence.

## Risks

Publication can still fail after commit; persist the existing failure contract.
A process crash between commit and publication can leave a queued run; durable
outbox recovery is outside this bounded pass.

## Rollback

Revert the follow-up commit. No migration or baseline change is involved.

## Completion Record

- **Completed:** 2026-09-11 (local implementation and verification)
- **PR:** not opened; hosted CI remains pending
- **Evidence:** [E-016](../execution/test_evidence.md)
- **Work log:** [2026-09-11](../execution/work_log.md)
- **Deviations:** T-410 was still uncommitted at entry; committed separately with
  approval before starting. Checks used Podman equivalents where host tooling or
  Compose was unavailable. Existing service-dependent skips are recorded in E-016.
- **Follow-ups:** R-031 hosted CI evidence and previously deferred scope remain open.
