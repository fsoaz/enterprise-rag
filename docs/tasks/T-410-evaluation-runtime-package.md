# T-410 — Extract the evaluation runtime from `evals/` tooling

| Field | Value |
| --- | --- |
| **ID** | `T-410` |
| **Phase** | `4 — Evaluation` |
| **Status** | `done` |
| **Branch** | `feat/T-410-evaluation-runtime-package` |
| **Size** | `M` |
| **Depends on** | `T-405`, `T-406`, `T-407`, `T-408` |
| **Blocks** | Merging the T-405→T-408 stack into `main`; `T-409` |

---

## Goal

The API and worker run the evaluation feature using only code and data their image
ships. `evals/` is again offline tooling that no product module imports, and a lint
contract plus an image import check keep it that way.

## Context

Evaluation became an API and Celery feature in T-405–T-407, but the report builder,
ranking metrics, gold-label resolution, and judge rubric stayed in `evals/harness`.
`api.routers.evals` imported it at module load, `worker.tasks.eval` at task
registration, and `llm.judge` found the rubric by walking up to the repository root.
`Dockerfile.api` never copies `evals/`, and CI only builds images, so no gate noticed.
`main` does not contain this coupling; it exists only on the unmerged stack.

- Design: [architecture.md § 11.1](../context/architecture.md#111-golden-dataset), [§ 16](../context/architecture.md#16-repository-layout), [ADR-016](../context/architecture.md#adr-016--the-evaluation-runtime-is-a-package-evals-is-offline-tooling)
- Standards: [conventions.md § 3–4](../standards/conventions.md#4-module-boundaries) — logic two apps share moves to `packages/`
- Prior findings: R-124 (this task), R-058 (mutable `0001_initial`)

## Acceptance Criteria

- [x] No module under `apps/*/src` or `packages/*/src` imports `evals`. `lint-imports` enforces it and fails when a violating import is added. *7 contracts kept; the injected `api.routers.evals -> evals.harness.metrics` import breaks `product-never-imports-evals` (E-015).*
- [x] The built API/worker image imports `api.main` and `worker.tasks.eval` and reads the judge rubric (CI `container-build`). *Passes on the T-410 image; the pre-change `f348059` image fails with `ModuleNotFoundError: No module named 'evals'` (E-015).*
- [x] `rubric_hash()` equals the SHA-256 recorded in `llm/judges/manifest.json` (`5b090686…`), so existing `judge_prompt_hash` values stay comparable. *Asserted by `test_judge.py` and read inside the image (E-015).*
- [x] Dataset registration and eval runs resolve source labels from `eval_source_labels`; no runtime path reads `evals/corpus.json` or fixture files. *The smoke flow registered label-based datasets and completed runs through the API and Celery (E-015).*
- [x] `eval_source_labels` is tenant-scoped with forced RLS; an integration test shows another tenant's context resolves nothing. *`test_labels.py` passed; catalog check `relrowsecurity`, `relforcerowsecurity`, policy, and grant all true (E-015).*
- [x] `make migrate-check` passes from an empty database (up → down → up → seed). *Run as the equivalent Alembic sequence against a disposable Podman Postgres, because no compose provider is installed (E-015).*
- [x] `make openapi-check` reports no change. *Both `openapi.json` files match `app.openapi()` (E-015).*
- [x] The smoke comparison passes `evals.harness.gate` against `evals/baselines/t407-smoke.json` without editing the baseline. *Gate passed with no violations; dataset hash and `hybrid_rrf` metrics equal the baseline (E-015).*

## Out of Scope

- Moving `_answer_metrics` out of `worker.tasks.eval`.
- The `-admin` acting-user fallback in `worker.tasks.eval._evaluate_item`.
- Rewriting `0001_initial` or any released migration.
- Any API request/response or SSE contract change; re-baselining.
- An eval dashboard or any `apps/web` change.

## Design Notes

- **`packages/evaluation`** holds `metrics` (ranking metrics), `report` (`build_report`, `ComparisonError`, paired bootstrap) and `labels` (`resolve_labels`, `bind_label`). It imports only `db`.
- **Stays in `evals/`:** the sweep runner and its configuration, the CLI entry points, CI orchestration, the gate, corpus/manifest/dataset loaders, fixtures, and datasets.
- **The rubric** moves byte-identical to `packages/llm/src/llm/judges/` and is loaded with `importlib.resources`.
- **Labels stay symbolic in datasets.** The offline corpus loader upserts `label → document_version_id` into `eval_source_labels`, and runtime reads that table. The dataset `content_sha256` is still computed over label-bearing items, so the committed baseline remains valid.
- **Rejected alternatives:**
  - *Packaging the corpus and fixtures:* this makes synthetic data a production dependency.
  - *Clients sending version UUIDs:* UUIDs differ per database, which breaks the reproducible dataset hash and the committed baseline.

## Files Expected to Change

| Path | Change |
| --- | --- |
| `packages/evaluation/**` | New package: `metrics`, `report`, `labels`, tests |
| `packages/llm/src/llm/judge.py`, `packages/llm/src/llm/judges/` | Rubric as package data |
| `packages/db/src/db/models.py`, `packages/db/migrations/versions/0006_eval_source_labels.py` | `EvalSourceLabel` + RLS migration |
| `apps/api/src/api/routers/evals.py`, `apps/worker/src/worker/tasks/eval.py` | Import from `evaluation` |
| `evals/harness/{compare,corpus,metrics,run}.py`, tests | Depend on `evaluation`; loader writes bindings |
| `pyproject.toml`, `apps/{api,worker}/pyproject.toml`, `uv.lock`, `infra/compose/Dockerfile.api` | Workspace member, dependencies, image `PYTHONPATH` |
| `.importlinter`, `.github/workflows/ci.yml` | Boundary contracts; image import check |
| `docs/…` | ADR-016, § 11.1, § 14.5, § 16, conventions § 4, testing § rubric location, review note, roadmap |

## Data / Migration Notes

- Tables touched: new `eval_source_labels`.
- Migration is reversible: yes (`DROP TABLE IF EXISTS`).
- Expand/contract needed: no (additive).
- Backfill required: only for a local database whose corpus was loaded before this change. Re-running `uv run python -m evals.harness.run --load-corpus` is idempotent. CI databases are always fresh.
- RLS policy added for the new tenant-scoped table: yes (`FORCE` + `tenant_isolation`, applied idempotently because `0001_initial` may already have created the table).

## Test Plan

| Tier | What is covered |
| --- | --- |
| Unit | Moved metric and report tests; rubric hash equals the recorded manifest SHA |
| Integration | `resolve_labels` / `bind_label`: idempotent rebind, unbound labels absent, RLS hides another tenant; existing eval API, temporal, and RLS suites |
| Contract | `make openapi-check`; import-linter contracts, including a deliberate violating import that must fail |
| Security | RLS on `eval_source_labels`; tenant context still derived from the run row |
| Eval | Smoke comparison + gate against the unchanged committed baseline |
| E2E | Built API image imports its runtime modules; Compose `api`/`worker` register and complete a run |

**Commands to run:**

```text
make lint typecheck
make test
make migrate-check
make test-integration
make openapi-check
docker build -f infra/compose/Dockerfile.api -t enterprise-rag-api:latest .
docker run --rm enterprise-rag-api:latest python -c "import api.main, worker.tasks.eval, llm.judge; llm.judge.rubric_text()"
```

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| A fresh database gets the table from `0001_initial` without RLS | High without mitigation | `0006` applies RLS unconditionally; `make migrate-check` from empty |
| A local database has no bindings and dataset registration returns 409 | Medium | Re-run the idempotent corpus loader |
| Rubric bytes change during the move and alter `judge_prompt_hash` | Low | `git mv`; test asserts the recorded SHA |

## Rollback

Revert the commits and run `alembic downgrade 0005_eval_execution`, which drops
`eval_source_labels`. The table holds only offline corpus bindings, so no product data
is lost.

---

## Completion Record

- **Completed:** `2026-09-11` (local; committed as `b6e68c1`)
- **PR:** pending; hosted CI not yet measured
- **Evidence:** [test_evidence.md](../execution/test_evidence.md) entry `E-015`
- **Work log:** [work_log.md](../execution/work_log.md) entry `2026-09-11`
- **Deviations from plan:** see E-015 for local tooling substitutions
- **Follow-ups raised:** T-411 (bounded complexity cleanup)
