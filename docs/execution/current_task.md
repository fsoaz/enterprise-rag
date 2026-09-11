# Current Task

> Exactly one task is `in_progress` at a time. Update this file when you start and when you finish.
> **Related:** [../tasks/README.md](../tasks/README.md) · [work_log.md](./work_log.md) · [../context/roadmap.md](../context/roadmap.md)

---

## Active

| Field | Value |
| --- | --- |
| Task | T-411 — Bound evaluation complexity after T-410 |
| File | [T-411-bounded-complexity-cleanup.md](../tasks/T-411-bounded-complexity-cleanup.md) |
| Status | done — local implementation and verification complete ([E-016](./test_evidence.md)); hosted CI remains pending |
| Branch | refactor/T-411-bounded-complexity-cleanup |
| Started | 2026-09-11 |
| Base | T-410 (`b6e68c1`, committed separately) |

T-410 resolves R-124 before the T-405→T-408 stack merges into `main`, which is the
baseline and does not contain the coupling.

Milestone A remains incomplete. The July 31 QA report records 21 defects fixed,
two intentional behaviors, and one fixed regression. Those fixes are committed;
the July 27 handoff's uncommitted-tree statement was stale. Historical evidence
remains in the QA reports and evidence log. No new CI run has been confirmed.
Live generation, judging, cost, and current retrieval quality remain unmeasured.

R-070, R-030, T-401, T-402, T-403, T-404, T-405, and T-406 are implemented locally on
stacked task branches. T-407's workflow and deterministic gate are implemented;
R-031 remains open until GitHub Actions runs the smoke job successfully. T-408's
chunking experiment is complete and its fixed-token default decision is recorded
in ADR-015. Remaining sequence: define and implement T-409, then release
demonstration.
The T-408 full eight-slice evaluation is complete. Paid generation, judging, and expansion
share a cumulative US$25 ceiling; no recurring nightly spend is authorized.
Use disposable databases and keep deterministic and real-model evidence separate.

R-058's mutable `0001_initial` remains a separate migration-history concern.
Do not rewrite released migrations as part of this work. Release readiness requires
all exit criteria to have measured evidence; unmet criteria remain blockers.

## Next Task

T-409 — sparse retrieval arm experiment (Q-2) is the next implementation task. Its
task file should be created and marked `in_progress` before code changes begin.

---

## Up Next (Milestone B)

| ID | Title |
| --- | --- |
| Phase 5 | Operations (budgets, OTel, degradation ladder, freshness scoring) |
| Phase 6b | Eval dashboard + full admin |
| Phase 7 | Terraform → ECS |

---

## Target: Milestone A

| Phase | Theme | Status |
| --- | --- | --- |
| 0 | Foundation | Done |
| 1 | Ingestion & versioning (PDF/MD/TXT) | Done (sync ingest + pipeline) |
| 2 | Retrieval core | Done |
| 3 | Generation & citations | Done (live LLM optional; extractive fallback) |
| 4 | Evaluation | Partial — T-401 through T-408 implemented; hosted CI evidence and later experiments outstanding |
| 6a | Chat UI + minimal admin | Done — auth, multi-turn, PT/EN, admin document management, frontend tests |

---

## Recently Completed

| Date | Task | Summary |
| --- | --- | --- |
| 2026-09-11 | T-411 | Dispatch ordering, canonical comparison, supported configuration, and deterministic gate scope; E-016 local evidence |
| 2026-09-11 | T-410 | Evaluation runtime extraction committed as `b6e68c1`; E-015 local evidence |
| 2026-09-10 | T-408 | Deterministic fixed-token/section-aware chunking experiment, full 320-item comparison, and ADR-015 decision to retain the fixed-token default |
| 2026-09-07 | T-406 | JSON-configured strategy sweeps, persisted child runs, model identity propagation, canonical comparison matrix, paired bootstrap significance, and Podman-backed integration evidence |
| 2026-09-07 | T-405 | Evaluation datasets, production-path worker execution, versioned Haiku judging, metrics, cost ledger reconciliation, idempotent retries, API contracts, and Podman-backed integration evidence |
| 2026-07-27 | — | Milestone A closing round: OIDC sign-in (ADR-013), real BGE-M3 + reranker weights, disposable test database, keyset pagination (ADR-014), multi-turn chat, PT/EN localization, admin document management, frontend test tier. Closed the 11 remaining QA findings |
| 2026-07-26 | — | QA review of Milestone A: 37 findings, 30 closed; ADR-012; R-062→R-074 |
| 2026-07-25 | — | Milestone A review remediation: R-009→R-029 fixed (RBAC wired, ACL on metadata reads, inference token enforced, stubs made inert, eval harness made real); R-030/R-031 open |
| 2026-07-25 | T-001→6a | Milestone A MVP: monorepo, Compose, RLS, auth, ingest, retrieval, chat, eval, UI |
| 2026-07-25 | T-004/T-005 | Auth tenant context + CI workflow |
| 2026-07-25 | T-002/T-003/T-006 | Compose, migrations+RLS, seed tenants |
| 2026-07-25 | T-001 | Monorepo scaffold |
| 2026-07-25 | — | Review remediation: 8 findings resolved, v1 split into two milestones |
| 2026-07-25 | — | Planning phase: `docs/` populated |
