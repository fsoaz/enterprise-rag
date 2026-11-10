# Current Task

> Exactly one task is `in_progress` at a time. Update this file when you start and when you finish.
> **Related:** [../tasks/README.md](../tasks/README.md) · [work_log.md](./work_log.md) · [../context/roadmap.md](../context/roadmap.md)

---

## Active

No implementation task is in progress. Validation/GitHub reconciliation completed
2026-11-09 against local HEAD and GitHub `main` at `353820d`.
See [E-019](./test_evidence.md#e-019--milestone-a-validation-and-github-reconciliation-2026-11-09).

T-413 is merged through [PR #5](https://github.com/fsoaz/enterprise-rag/pull/5):
fix `6b3e2c5`, merge `353820d`. Its PR CI run
[37093710003](https://github.com/fsoaz/enterprise-rag/actions/runs/37093710003)
passed the production-path smoke comparison **and** regression-threshold step.
Post-merge CI [37094247061](https://github.com/fsoaz/enterprise-rag/actions/runs/37094247061)
also passed. T-407's hosted acceptance criterion is met; R-031 is resolved.
T-410/T-411 and T-412 documentation edits are also merged; earlier statements that
they were only local or uncommitted are superseded. T-412's guide walkthrough
acceptance criterion remains unverified; CI does not exercise that walkthrough.

Scheduled full evaluation
[42611175399](https://github.com/fsoaz/enterprise-rag/actions/runs/42611175399)
passed on the same `main` SHA on 2026-11-09. This is deterministic stub evidence.
The scheduled workflow does not invoke `evals.harness.gate`; its success is not the
basis for closing R-031 or a claim of live-model quality.

Milestone A remains incomplete. Real-weights strategy comparison, live generation,
judging, injection rate, latency/cost evidence, and outstanding roadmap exit
criteria still need measurement. The deliberate-regression unit test exercises
altered metric reports; a hosted end-to-end retrieval mutation has not been verified.
R-058's mutable `0001_initial` and R-132's milestone scope conflict remain separate
concerns. No migration history or milestone requirements were changed here.

## Next Task

T-409 — sparse retrieval arm experiment (Q-2). **No hosted-CI dependency gate
remains before starting it.** Before code changes, create its task file, define
its experiment/acceptance criteria, and mark it `in_progress` here. It is not
started by this reconciliation. T-408/ADR-015 retains fixed-token chunking.

The historical experiment authorization caps paid generation, judging, and
expansion cumulatively at US$25; no new paid run or recurring nightly spend is
authorized by this reconciliation. Use disposable databases and keep deterministic
and real-model evidence separate. Milestone exit validation remains a release gate,
not evidence supplied by starting T-409.

---

## Up Next (Milestone B)

| ID | Title |
| --- | --- |
| Phase 5 | Operations (budgets, OTel, degradation ladder, freshness scoring) |
| Phase 6b | Eval dashboard + full admin |
| Phase 7 | Terraform → ECS |

---

## Target: Milestone A

The phase labels below describe implementation coverage. Release completion still
requires the measured exit criteria in [the roadmap](../context/roadmap.md).

| Phase | Theme | Status |
| --- | --- | --- |
| 0 | Foundation | Done |
| 1 | Ingestion & versioning (PDF/MD/TXT) | Done (sync ingest + pipeline) |
| 2 | Retrieval core | Done |
| 3 | Generation & citations | Done (live LLM optional; extractive fallback) |
| 4 | Evaluation | Partial — T-401 through T-408, T-410, and T-411 implemented; hosted CI verified (E-019); T-409 and live validation outstanding |
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
