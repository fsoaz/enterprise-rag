# Current Task

> Exactly one task is `in_progress` at a time. Update this file when you start and when you finish.
> **Related:** [../tasks/README.md](../tasks/README.md) · [work_log.md](./work_log.md) · [../context/roadmap.md](../context/roadmap.md)

---

## Active

| Field | Value |
| --- | --- |
| **Task** | — |
| **File** | — |
| **Phase** | Milestone A complete (scaffold through 6a) |
| **Status** | idle |
| **Branch** | `chore/T-001-monorepo-scaffold` (carries Phase 0–6a MVP) |
| **Started** | — |
| **Blockers** | None |

### Next step

Milestone A MVP is implemented on this branch and has been through an implementation review — 23 findings, 21 fixed (R-009 → R-029 in [review_notes.md](./review_notes.md)). Suggested follow-ups, highest value first:

1. **Close R-030** — retrieval has no `as_of` filter, so as-of-date questions cannot be answered. The `versioned` eval slice scores `recall@10 = 0.50` because of it.
2. Swap inference stubs for real BGE-M3 / reranker weights (T-105 / T-206), then move the default strategy back to `hybrid_rerank` and confirm the Phase 2 exit criterion with numbers.
3. **Close R-031** — wire the eval harness into CI; needs an `inference` service in the `integration-db` job.
4. Set a real `ANTHROPIC_API_KEY` for native citations, which also unlocks the answer-quality, latency, and cost columns of the quality snapshot (all `n/m` today).
5. Split into reviewable PRs per phase (or land as one portfolio PR).
6. Begin Milestone B only after A is demoed.

### Notes

RLS backstop, ingest/search, and chat paths verified — **39 passed, 0 skipped** with the environment loaded ([E-003](./test_evidence.md)). Note the suite reports 32 passed + 3 skipped without Postgres/MinIO/inference up; always state which.

The eval harness now scores live retrieval against a real fixture corpus (`--load-corpus`) and exits non-zero rather than reporting synthetic metrics. First real numbers: overall `recall@10 = 0.909`.

Embedding and rerank remain stubs but degrade to no-ops rather than fabricating signal ([ADR-009](../context/architecture.md#adr-009--a-stub-degrades-to-a-no-op-never-to-a-wrong-signal)); the dense arm therefore contributes no semantic signal yet.

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
| 4 | Evaluation | Partial — harness scores live retrieval; CI gate (R-031) and answer-quality judges outstanding |
| 6a | Chat UI + minimal admin | Done |

---

## Recently Completed

| Date | Task | Summary |
| --- | --- | --- |
| 2026-07-25 | — | Milestone A review remediation: R-009→R-029 fixed (RBAC wired, ACL on metadata reads, inference token enforced, stubs made inert, eval harness made real); R-030/R-031 open |
| 2026-07-25 | T-001→6a | Milestone A MVP: monorepo, Compose, RLS, auth, ingest, retrieval, chat, eval, UI |
| 2026-07-25 | T-004/T-005 | Auth tenant context + CI workflow |
| 2026-07-25 | T-002/T-003/T-006 | Compose, migrations+RLS, seed tenants |
| 2026-07-25 | T-001 | Monorepo scaffold |
| 2026-07-25 | — | Review remediation: 8 findings resolved, v1 split into two milestones |
| 2026-07-25 | — | Planning phase: `docs/` populated |
