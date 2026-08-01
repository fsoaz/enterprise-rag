# Current Task

> Exactly one task is `in_progress` at a time. Update this file when you start and when you finish.
> **Related:** [../tasks/README.md](../tasks/README.md) · [work_log.md](./work_log.md) · [../context/roadmap.md](../context/roadmap.md)

---

## Active

| Field | Value |
| --- | --- |
| **Task** | — |
| **File** | — |
| **Phase** | Milestone A complete — security & correctness pass, QA round (37 findings), closing round (the 11 that remained) |
| **Status** | idle — changes uncommitted on the working tree |
| **Branch** | `main` (working tree on commit `104facc`) |
| **Started** | — |
| **Blockers** | None blocking release. Two things unmeasured rather than broken: no CI run on this tree, and no live `ANTHROPIC_API_KEY`, so answer quality is untested. |

### Next step

The closing round shipped OIDC sign-in, real BGE-M3 / BGE-reranker-v2-m3 weights, a
disposable integration database, keyset pagination, multi-turn chat, PT/EN localization,
admin document management, and a frontend test tier. That closes `IS-03`, `IS-07`, `IS-08`,
`IS-09`, `IS-11`, `IS-12`, `IS-20`, `IS-21`, `IS-23`, `IS-24` and `IS-32` from
[qa_report_2026-07-26.md](./qa_report_2026-07-26.md) — every finding that was still open or
partial. Registered as R-075 → R-077, with R-059, R-061, R-071 and R-072 updated in
[review_notes.md](./review_notes.md). Evidence: [E-008](./test_evidence.md).

Next work, highest value first:

1. **Commit and push, then confirm CI.** None of this has run in GitHub Actions. R-059 and R-061 were failures seen *only* in CI, so they are recorded as `resolved (local)` and stay that way until Actions is green on this commit. First because it is the step that can invalidate the two claims above it.
2. **Set a real `ANTHROPIC_API_KEY`.** Still the only way to fill the answer-quality, latency, cost and injection-success columns — all `n/m`, and all of what remains of Milestone A's exit criteria.
3. **Re-measure retrieval against real weights.** The embedder changed, so every retrieval number in [E-007](./test_evidence.md) is superseded rather than a baseline. Needs a `--load-corpus` run on a reset database.
4. **Finish R-070.** Two of its three named gaps are closed by frontend tests. The third is not: nothing drives `/chat/completions` with inference unreachable and asserts `503 retrieval-unavailable` — `test_chat.py` *tolerates* 503 in a status set rather than requiring it, which is the same "asserts the wrong thing" shape the finding is about.
5. **Close R-031** — wire the eval harness into CI. The OpenAPI and generated-types drift checks now run in `typecheck` and `web-test` runs Vitest, so the eval gate is the only remaining hole in the CI table.
6. **Close R-030** — retrieval has no `as_of` filter, so as-of-date questions cannot be answered.
7. **Rewrite `0001_initial` as explicit DDL.** It still uses `Base.metadata.create_all()`, so every model-level index change silently rewrites released migration history. `IF NOT EXISTS` in 0002/0003 contains the symptom; this removes the cause (R-058).
8. Begin Milestone B only after A is demoed.

### Notes

Unit **74 passed, 1 skipped, 14 deselected**; integration **11 passed, 3 skipped**;
frontend **9 passed** at 72.31% statements ([E-008](./test_evidence.md)). All local, with
mypy, ruff, import-linter, biome, tsc, `next build`, `make openapi-check` and compose
validation green. **There is no CI result for this tree** — the last recorded CI run is
[E-005](./test_evidence.md), against an older commit. Always state the environment and the
skip count.

**Retrieval: no current number is quotable.** The `recall@10 = 0.909` figure quoted in an
earlier revision of this file did not reproduce; re-measured on 2026-07-26 it was overall
**0.364**, `crosslingual` **0.000**. That measurement was itself taken under stub
embeddings, and the embedder has since been replaced with real BGE-M3 — so it is
superseded too, in the pessimistic direction. Quote neither. Quote no retrieval number that
was not produced by a `--load-corpus` run on a reset database with the current backend.

Five rules came out of these passes and are now ADRs: thresholds compare **normalized**
values, never raw scores ([ADR-010](../context/architecture.md#adr-010--thresholds-compare-normalized-values-never-raw-scores));
a signal nothing reads is **not a control** ([ADR-011](../context/architecture.md#adr-011--a-signal-that-nothing-reads-is-not-a-control));
degraded-mode evidence is lexical or it does not exist ([ADR-012](../context/architecture.md#adr-012--degraded-mode-evidence-is-lexical-or-it-does-not-exist));
the browser never holds a token ([ADR-013](../context/architecture.md#adr-013--the-browser-never-holds-a-token));
and pagination cursors encode a position, not an offset ([ADR-014](../context/architecture.md#adr-014--pagination-cursors-encode-a-position-not-an-offset)).

A sixth pattern is a recurring theme rather than an ADR: **the convenient failure mode is
usually the wrong one** (R-015, R-016, R-058, R-071, R-075). An embedder without weights
falling back to hashes, a suite using whatever database is configured, a migration skipping
an object it assumes exists — each keeps the system working, and that is the problem. When
a required dependency is missing, fail at startup and name it.

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
| 6a | Chat UI + minimal admin | Done — auth, multi-turn, PT/EN, admin document management, frontend tests |

---

## Recently Completed

| Date | Task | Summary |
| --- | --- | --- |
| 2026-07-27 | — | Milestone A closing round: OIDC sign-in (ADR-013), real BGE-M3 + reranker weights, disposable test database, keyset pagination (ADR-014), multi-turn chat, PT/EN localization, admin document management, frontend test tier. Closed the 11 remaining QA findings |
| 2026-07-26 | — | QA review of Milestone A: 37 findings, 30 closed; ADR-012; R-062→R-074 |
| 2026-07-25 | — | Milestone A review remediation: R-009→R-029 fixed (RBAC wired, ACL on metadata reads, inference token enforced, stubs made inert, eval harness made real); R-030/R-031 open |
| 2026-07-25 | T-001→6a | Milestone A MVP: monorepo, Compose, RLS, auth, ingest, retrieval, chat, eval, UI |
| 2026-07-25 | T-004/T-005 | Auth tenant context + CI workflow |
| 2026-07-25 | T-002/T-003/T-006 | Compose, migrations+RLS, seed tenants |
| 2026-07-25 | T-001 | Monorepo scaffold |
| 2026-07-25 | — | Review remediation: 8 findings resolved, v1 split into two milestones |
| 2026-07-25 | — | Planning phase: `docs/` populated |
