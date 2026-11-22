# Evaluation and live validation

The hosted smoke job checks deterministic retrieval regressions and access
controls on 48 items. The scheduled full job publishes a comparison across
320 items and eight slices. Both use stub inference and extractive fallback.
Use the [local deterministic walkthrough](local-development.md#run-the-deterministic-evaluation-locally)
to reproduce those checks and the steps below to collect evidence for the
[release targets](../context/product.md#7-success-metrics).

## Compare retrieval with real BGE weights

1. Use a fresh, disposable evaluation database with the seeded Acme identities
   and the committed synthetic fixtures. Follow the
   [disposable database setup](local-development.md#run-the-deterministic-evaluation-locally)
   for database creation, role initialization, migration, and seeding. Start
   inference, API, worker, and web processes with the
   [separate-process startup commands](local-development.md#run-processes-separately).
   Use the disposable database URLs in the API, worker, migration, seed, and
   harness environments. Keep `DEV_AUTH_BYPASS=false` and
   `ANTHROPIC_API_KEY` at its placeholder during
   retrieval-only work. Set `INFERENCE_BACKEND=bge` consistently and remove any
   stub model or version overrides.
2. Wait for inference `GET /ready`, then check the `model` and `version` fields
   returned by authenticated `POST /v1/embed` and `POST /v1/rerank` probes
   against the intended models. The defaults are `BAAI/bge-m3` and
   `BAAI/bge-reranker-v2-m3`, both with the service label `bge-v1`. Use the
   configured inference service token and synthetic probe inputs such as
   `{"texts":["policy summary"],"mode":"query"}` for embedding and
   `{"query":"policy summary","documents":["A policy summary."],"top_k":1}`
   for reranking. Record the returned identities and the weights revisions if
   known.
3. Rebuild the fixture corpus under that backend and save both retrieval reports.
   Run from the repository root with the disposable database settings exported
   as above.

```bash
uv run --no-sync --env-file .env python -m evals.harness.run \
  --load-corpus --strategy hybrid_rrf --top-k 10 --verbose > /tmp/eval-bge-rrf.json
uv run --no-sync --env-file .env python -m evals.harness.run \
  --strategy hybrid_rerank --top-k 10 --verbose > /tmp/eval-bge-rerank.json
```

These reports score retrieved fixture source versions. Compare recall@10,
nDCG@10, and MRR@10 overall and by slice, including the cross-lingual breakdown
by question language. For the candidate-pool recall@50 measurement, repeat
the pre-rerank `hybrid_rrf` run with `--top-k 50` and compute recall at 50 from
the per-item source labels using the release target's metric definition.
Record missing coverage and deviations in scoring units. If the harness exits
with an exclusion failure after writing the report, retain that result for
review. It measures which sources reached retrieval. Live adversarial outcomes
are measured separately below.

## Evaluate answers with live generation and judging

Agree on an explicit spend limit and run size before starting the worker with
an Anthropic key in its environment. Keep the tenant budget enabled, estimate generation,
judging, and any expansion calls, and monitor cumulative spend between runs.
The rolling tenant check reads spend already recorded in the ledger. Use an
approved provider-side limit or bound the workload using a conservative
maximum cost per item for the overall spend cap.

Sign in as the seeded Acme admin through OIDC. The endpoints below use the
FastAPI paths. From the signed-in web origin, send the same requests through
`/api/backend/api/v1/…`. The browser session cookie lets the BFF attach the
authorization header server-side. Use the request and response schemas in the
[OpenAPI contract](../../openapi.json).

Prepare the dataset registration body from the validated full golden set.

```bash
uv run --no-sync python - <<'PY' > /tmp/eval-live-dataset.json
import json
from pathlib import Path

from evals.harness.ci import select_items

print(json.dumps({
    "name": "milestone-a-live",
    "version": "full-v1",
    "items": select_items(Path("evals/datasets"), mode="full"),
}))
PY
```

1. Register that body with `POST /api/v1/evals/datasets`. Save the returned
   `id`, `content_sha256`, and `item_count`. Reuse the registered dataset for
   both strategies. Its source labels and acting users resolve inside Acme.
2. Submit the baseline with `POST /api/v1/evals/runs` using the dataset UUID.
   Substitute the model identities you verified if they differ from the defaults.

   ```json
   {
     "dataset_id": "<registered dataset UUID>",
     "strategy": "hybrid_rrf",
     "embedding_model": "BAAI/bge-m3",
     "reranker": null,
     "generator_model": "claude-opus-5",
     "params": {
       "embedding_model_version": "bge-v1",
       "retrieval": {"top_k": 10, "retrieval_k": 50, "rrf_k": 60}
     }
   }
   ```

3. Poll `GET /api/v1/evals/runs/{id}` until terminal. After checking coverage
   and spend, submit the same request with `strategy` set to `hybrid_rerank`,
   `reranker` set to `BAAI/bge-reranker-v2-m3`, and
   `params.reranker_version` set to the verified reranker version.
4. Fetch `GET /api/v1/evals/runs/{id}/results` for each run, following
   `next_cursor` until it is null. Once both runs are complete, fetch
   `GET /api/v1/evals/runs/compare?ids={rrf_id},{rerank_id}`, with the baseline
   ID first. Save the coverage and per-slice deltas. Use reported model and
   verdict fields and the generation and judge ledger entries to verify which
   items reached each live call. Count fallback, skipped judging, and failed
   items in the report. Label failed or incomplete runs with their coverage.

Report faithfulness, citation precision, relevance, unsupported-answer rate,
and correct abstention with their denominators. The worker uses expected-fact
string matches for relevance and gold-source membership for citation
precision. Its `unsupported_answer_rate` field counts unsupported verdicts,
which lead to abstention. Review emitted PT and EN answers and their cited
spans to measure unsupported answers actually served and to assess semantic
accuracy against the release definitions. Compute correct abstention on the
unanswerable slice for comparison with the product target.

Use the dedicated tenant and permission checks to report leakage and ACL
bypass against their zero thresholds. The worker initializes its
`tenant_leakage` field to zero and counts hits on each item's exclusion list
in `acl_bypass`. Report the checks and the covered cases alongside those fields.

## Measure latency and cost on the authenticated chat path

For approved live chat measurements, start the API with the Anthropic key in
its server-side environment. Use the `dev-cpu` or `cloud-gpu` workload defined in the
[performance and cost targets](../context/product.md#74-performance--cost).
Record corpus size, tenants, concurrency, hardware, cache state, request
configuration, network path, and actual model. If the environment differs from
the profile, publish the measurements with the actual configuration. For
example, chat has no per-request `max_tokens` option for setting the profile's
token cap.

- Time from request start through the `done` event from
  `POST /api/v1/chat/completions`. Use the stream's verdict to identify verified
  primary-path answers and report their p95. Report sample sizes, abstentions,
  fallbacks, errors, and cold-start runs alongside that result.
- Measure retrieval-only p95 on a matching workload. Use retrieval stage
  timing and a rerank span where available. Evaluation worker retrieval timings
  describe the workload that produced them. Mark the profile's retrieval or
  rerank target pending when matching measurements are missing.
- Use the `query_id` from `done` to reconcile chat charges against the
  tenant-scoped `cost_ledger`. Sum the ledgered calls for each query before
  computing median cost per query. Report cache usage and how hit rate was
  derived. Track evaluation generation and judge spend separately.

## Review live adversarial outcomes

Use the committed injection slice and its companion documents with real
generation on the authenticated chat path. Use each item's acting identity
and `as_of` value where specified. Review emitted answers and citations
against the expected outcome for each case. Record attempts,
successes, blocked or abstained cases, and cases with missing observations.
Report the observed success count, denominator, and rate against the release
target. With 40 cases, one success is 2.5%, and zero successes describe only
the observed sample. Keep retrieval exclusion counts as their own measure.
[Adversarial evaluation policy](../standards/testing.md#75-adversarial-evaluation-probabilistic)

## Record the evidence

Add a dated entry to the [evidence log](../execution/test_evidence.md) with the
commit, dataset version and hash, fixture and chunking configuration, actual
model identities and versions, judge rubric hash, run IDs, report locations,
benchmark profile, and aggregate and per-slice results. Record omissions and
any fallback or incomplete cases. State which existing release criteria were
met and which remain pending. Retain deterministic CI results under their own
run IDs.
