# T-406 — Strategy comparison runner

| Field | Value |
| --- | --- |
| ID | T-406 |
| Phase | 4 — Evaluation |
| Status | done |
| Branch | feat/T-406-strategy-comparison |
| Depends on | T-405 |
| Blocks | T-407, T-408, T-409 |

## Goal

Execute a configurable Cartesian sweep of retrieval strategies against one immutable
dataset, persist every child run through the T-405 worker path, and expose a
deterministic comparison matrix with paired statistical significance.

## Acceptance criteria

- [x] JSON configuration is strictly validated and expands strategies, embedding
  identities/endpoints, rerankers, and retrieval parameters deterministically.
- [x] The default sweep includes `hybrid_rrf`, `dense_only`, `lexical_only`, and
  `hybrid_rerank`, with `hybrid_rrf` as the CLI baseline.
- [x] Child runs persist the complete sweep selection in `EvalRun.params`; retrieval
  validates configured embedding and reranker identities at the inference boundary.
- [x] The canonical API endpoint returns ordered metadata, dataset compatibility,
  baseline-relative overall/per-slice metrics, coverage, confidence intervals, and
  deterministic significance flags.
- [x] Incomplete, incompatible, tenant-mismatched, or missing-result comparisons
  fail with RFC 7807 conflict responses.
- [x] Paired bootstrap uses aligned item IDs, 10,000 deterministic resamples by
  default, and preserves null significance where observations cannot be paired.

## Out of scope

Dashboard UI, CI regression gates, new comparison tables, paid model calls, and
experiment-specific decisions remain in T-407 through T-409.

## Runner configuration

The runner accepts a strict JSON file and writes the report to stdout or `--output`:

```json
{
  "dataset_id": "<dataset UUID>",
  "strategies": ["hybrid_rrf", "dense_only", "lexical_only", "hybrid_rerank"],
  "embedding_models": [{"name": "BAAI/bge-m3", "version": "stub-v0", "endpoint": "http://localhost:8001"}],
  "rerankers": [{"name": "identity-rerank-test-stub", "version": "stub-v0"}],
  "retrieval_params": [{"top_k": 8, "retrieval_k": 50, "rrf_k": 60}]
}
```

Run it with `python -m evals.harness.compare --config comparison.json --output report.json`.

The generated report is deterministic for the same persisted result rows. It keeps
the ordered child-run metadata and dataset compatibility information, then exposes
overall and per-slice metric values, signed and absolute deltas from the selected
baseline, `ci_lower`/`ci_upper` bounds, `significant`, and complete item/result
coverage. The API equivalent is
`GET /api/v1/evals/runs/compare?ids=<run-id>,<run-id>[,<run-id>...]`; its first ID
is the baseline. The existing two-run compatibility route is retained.

## Verification

Deterministic harness, retrieval identity, worker/API tests, OpenAPI synchronization,
and the disposable-Postgres integration suite are recorded in E-011.
