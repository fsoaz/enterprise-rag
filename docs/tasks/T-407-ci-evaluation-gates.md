# T-407 — CI evaluation gates

| Field | Value |
| --- | --- |
| ID | T-407 |
| Phase | 4 — Evaluation |
| Status | in_review |
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
  Phase 4 thresholds: two-point maximum drops for recall@10, nDCG@10, faithfulness,
  and citation precision; one-point maximum increase in unsupported-answer rate;
  three-point maximum drop in correct-abstention rate; and zero tenant leakage or
  ACL bypass.
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
- [ ] GitHub Actions `eval-smoke` has passed on the implementation commit.

## Verification

Focused gate/comparison/worker tests and the disposable service path pass locally.
The first hosted GitHub Actions smoke run remains to be verified; R-031 therefore
remains open until that run is green.

## Out of scope

Live Anthropic generation and judging, paid calls, chunking experiments, sparse
retrieval experiments, and the evaluation dashboard.
