# T-407 — CI evaluation gates

| Field | Value |
| --- | --- |
| ID | T-407 |
| Phase | 4 — Evaluation |
| Status | done — merged; hosted acceptance verified in E-019 |
| Depends on | T-406 |
| Blocks | T-408, T-409 |

## Goal

Run the production evaluation path in GitHub Actions with deterministic stub
inference, and block pull requests when the known-good smoke baseline regresses.

## Implementation

- `.github/workflows/ci.yml` adds `eval-smoke`, with disposable Postgres and Redis,
  the stub inference service, API, Celery worker, migrations, seed data, corpus
  loading, and the T-406 four-strategy comparison.
- `evals/harness/ci.py` validates the complete committed corpus, selects six items
  per slice for a deterministic 48-item PR run, registers the immutable dataset,
  and writes an artifact envelope containing the comparison report and metadata.
- `evals/harness/gate.py` validates dataset/config compatibility and enforces the
  current T-411 thresholds: two-point maximum drops for recall@10 and nDCG@10,
  and zero tenant leakage or ACL bypass in every strategy. Answer-quality metrics
  remain report-only in deterministic stub runs.
- `.github/workflows/eval-full.yml` runs the complete 320-item, eight-slice sweep
  on a schedule and retains the report without paid model calls.
- `evals/baselines/t407-smoke.json` records the deterministic stub configuration
  and smoke dataset identity used by the PR gate.

## Acceptance criteria

- [x] The PR workflow starts Postgres, Redis, stub inference, API, and worker and
  executes the committed corpus through the production path.
- [x] The smoke subset is deterministic and covers all eight slices (48 items).
- [x] Comparison reports are published as artifacts; full reports are retained by
  the scheduled workflow.
- [x] Missing metrics, incompatible baselines, deliberate quality regressions, and
  non-zero security metrics fail in focused unit tests.
- [x] GitHub Actions `eval-smoke` has passed on the implementation commit —
  PR #5 head `6b3e2c5`, run 37093710003; post-merge `353820d`, run 37094247061.

## Verification

Focused gate/comparison/worker tests and the disposable service path pass locally.
Hosted PR and post-merge smoke comparison and threshold steps are verified green
in [E-019](../execution/test_evidence.md#e-019--milestone-a-validation-and-github-reconciliation-2026-11-09); R-031 is resolved.
Deliberate metric-regression unit coverage is distinct from a hosted end-to-end
retrieval mutation, which has not been verified.

## Out of scope

Live Anthropic generation and judging, paid calls, chunking experiments, sparse
retrieval experiments, and the evaluation dashboard.
