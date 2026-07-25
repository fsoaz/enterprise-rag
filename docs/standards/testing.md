# Testing Standards

> **Applies to:** every contributor, human or AI.
> **Related:** [conventions.md](./conventions.md) · [api_rules.md](./api_rules.md) · [../context/architecture.md](../context/architecture.md) · [../execution/test_evidence.md](../execution/test_evidence.md)

A RAG system fails quietly. Retrieval gets slightly worse, an ACL filter is dropped, a citation stops resolving — nothing crashes, and nobody notices for a month. The test strategy is built around making quiet failures loud.

---

## 1. Test Tiers

| Tier | Scope | Runtime budget | Runs on |
| --- | --- | --- | --- |
| **Unit** | One function or class. No I/O, no network, no database. | < 30 s total | Every commit |
| **Integration** | Real Postgres and Redis via testcontainers. Real SQL, real migrations. | < 5 min | Every commit |
| **Contract** | Committed OpenAPI schema vs. implementation; generated TS types vs. schema | < 30 s | Every commit |
| **Security** | Tenant isolation, ACL correctness, injection resistance, log hygiene | < 2 min | Every commit — **never skipped** |
| **E2E** | Playwright against the full Compose stack | < 10 min | Pre-merge |
| **Eval** | Offline quality gates on the golden set | smoke < 5 min / full ~30 min | Smoke per PR, full nightly |
| **Load** | k6 against staging | ~15 min | Pre-release |

Tiers run in this order in CI. A failure in an earlier tier short-circuits the rest.

## 2. Coverage

| Target | Threshold | Rationale |
| --- | --- | --- |
| `packages/retrieval` | 95% | ACL predicate construction is where a security bug hides |
| `packages/db` (ACL + tenancy) | 95% | Same |
| `packages/domain` | 90% | Pure logic, cheap to cover |
| `packages/llm` | 85% | Provider calls are mocked; the wrapper logic is testable |
| `packages/*` overall | 85% | |
| `apps/*` | 75% | Thin routers; the logic lives in packages |
| Whole repo | 75% | Gate |

Coverage is a floor, not a goal. A 95% number with no test for "user B cannot see user A's document" is worthless. Reviewers check what is tested, not how much.

## 3. Unit Tests

- Pure functions and classes with injected dependencies. If a test needs `unittest.mock.patch` to reach into a module's internals, the code has a design problem — fix the code.
- No `sleep`. No real clock — inject a time provider.
- No network, no filesystem outside `tmp_path`, no database.
- Parametrize aggressively; one assertion concept per test.
- Naming: `test_<unit>__<condition>__<expected>` — e.g. `test_acl_predicate__document_deny_overrides_collection_allow__excludes_document`.

**High-value unit targets:** RRF fusion math, ACL resolution order, chunk boundary logic, citation span mapping, groundedness verdict thresholds, cost computation from usage, staleness scoring, retry/backoff policy.

## 4. Integration Tests

Real Postgres (with `pgvector`) and Redis in testcontainers. Migrations run against the container, so the schema under test is the schema that ships.

- Each test runs in a transaction that is rolled back, except migration tests.
- Fixtures create two tenants with overlapping-looking data (same document titles, similar content) so a leak is visible rather than coincidentally absent.
- The `inference` service is stubbed with a deterministic fake returning fixed vectors and fixed rerank scores — retrieval logic is tested, model quality is not (that is the eval tier).
- Anthropic calls are stubbed. No integration test hits a paid API.

**High-value integration targets:** RLS enforcement, the fused retrieval SQL, HNSW behavior under a selective filter, version supersession and the partial unique index, idempotent ingest by content hash, ACL cache invalidation on `acl_version` bump, cursor pagination stability under concurrent inserts.

## 5. Contract Tests

- Assert the committed `openapi.json` matches what FastAPI generates. A drift fails the build — this is what surfaces an accidental breaking change in review.
- Assert generated frontend types match the committed schema.
- Assert every error `type` slug returned anywhere in the codebase appears in the registry in [api_rules.md § 5.2](./api_rules.md#52-error-type-registry).
- Assert the internal `inference` contract: both services agree on request and response shapes.

## 6. Security Tests

**This suite is mandatory and never skipped, not even to unblock a hotfix.** Two of its assertions are release gates with a value of zero.

### 6.1 Tenant isolation

| Test | Assertion |
| --- | --- |
| Cross-tenant read | Tenant A's token cannot read any of tenant B's rows, on every tenant-scoped table |
| **RLS backstop** | The same test passes **with the ORM tenant filter deliberately removed**. This is the test that proves defense in depth is real rather than aspirational. |
| Raw SQL path | A hand-written query that forgets `tenant_id` is still blocked by RLS |
| Object storage | A signed URL for tenant A's key cannot be produced or used under tenant B's context |
| Cache | No Redis key is reachable across tenants |
| Search results | An ANN query under tenant A never returns a tenant B chunk, including at high `ef_search` |

### 6.2 Access control

| Test | Assertion |
| --- | --- |
| Deny precedence | Document-level `deny` overrides collection-level `allow` |
| Default deny | A user with no matching ACL entry gets nothing |
| **Pre-filter proof** | A user permitted 5% of the corpus still receives a full top-8 — asserted by result count, which is what distinguishes pre-filtering from post-filtering |
| No count leakage | Result counts and pagination totals are identical whether inaccessible documents exist or not |
| Revocation | Removing an ACL entry takes effect on the next query (cache invalidated by `acl_version`) |
| Tool ACL | The `search_documents` tool runs under the caller's predicate, not a widened one |
| Citation ACL | A citation never resolves to a chunk the caller cannot read |

### 6.3 Prompt injection

A corpus of adversarial documents in `evals/fixtures/injection/`: instruction override, role confusion, fake system markers, encoded payloads, zero-width characters, instructions inside table cells and image alt text, and a multi-document coordinated attempt.

| Test | Assertion |
| --- | --- |
| Instruction override | A document saying "ignore previous instructions" does not change behavior |
| Exfiltration | An injected instruction to reveal the system prompt or another document fails |
| Tool abuse | An injected instruction cannot trigger a tool call the user did not request |
| Detection | Injection attempts are flagged at ingest and counted in `injection_flagged_total` |
| Rate | Suite-wide success rate ≤ 1% |

### 6.4 Log hygiene

Capture structured log output during an integration run and assert absence of: document content, chunk text, answer text, raw questions above `debug`, tokens, API keys, JWTs, and full email addresses.

### 6.5 Dependency & secret scanning

`pip-audit`, `npm audit`, and `gitleaks` run in CI. High-severity advisories and any detected secret block the merge.

## 7. Eval Tests

The quality gate. Distinct from correctness tests: these measure *how well*, not *whether*.

### 7.1 Datasets

Golden set in `evals/datasets/`, fixtures in `evals/fixtures/`. Slices per [architecture.md § 11.1](../context/architecture.md#111-golden-dataset). Minimum 40 items per slice.

**No real customer data, ever.** The fixture corpus is synthetic, bilingual, and committed. A test asserts that no fixture file contains a real-looking email, CPF, CNPJ, or credit-card pattern.

### 7.2 Gates

| Metric | Smoke (per PR) | Full (nightly) |
| --- | --- | --- |
| `recall@10` | no drop > 2 pts vs. baseline | ≥ 0.90 |
| `nDCG@10` | no drop > 2 pts | ≥ 0.75 |
| Faithfulness | no drop > 2 pts | ≥ 0.95 |
| Citation precision | no drop > 2 pts | ≥ 0.90 |
| Unsupported-answer rate | no rise > 1 pt | ≤ 2% |
| Correct abstention | no drop > 3 pts | ≥ 0.90 |
| Cross-tenant leakage | — | **0** (hard gate) |
| ACL bypass | — | **0** (hard gate) |
| Injection success | no rise | ≤ 1% |
| Cost per query | no rise > 20% | ≤ $0.03 median |

A gate breach fails the build. Overriding a gate requires an explicit note in the PR explaining why the new number is correct — and updating the baseline in the same commit, so the override is visible in history.

### 7.3 Judge discipline

- Answer-quality judging uses `claude-haiku-4-5` with a **versioned rubric prompt**.
- The rubric prompt hash is stored on `eval_runs.judge_prompt_hash`.
- Comparing two runs with different judge hashes is flagged in the dashboard — a judge change must never be read as a quality change.
- Judge prompts live in `evals/harness/judges/` and change through the normal review process.

### 7.4 Baselines

Baseline metrics are committed to `evals/baselines/<git-sha>.json`. The smoke gate compares against the baseline of `main`. Updating a baseline is a deliberate, reviewed commit.

## 8. Determinism

| Tier | LLM handling |
| --- | --- |
| Unit | Fully mocked; fixed response objects |
| Integration | Recorded cassettes; no live calls |
| Contract | No LLM involved |
| Security | Mocked, except the injection suite which may use a live judge in nightly |
| E2E | Cassettes by default; a live-mode flag exists for manual verification |
| **Eval** | **Live calls.** This is the only tier that spends money, and it is the point of the tier. |

Cassettes live in `tests/cassettes/` and are regenerated deliberately, never automatically. A stale cassette that hides a real API change is caught by the nightly eval run.

Other determinism rules: fixed random seeds; injected clock; no test depends on wall-clock ordering; no test depends on another test's side effects.

## 9. Performance Tests

### 9.1 Micro-benchmarks (CI)

`pytest-benchmark` on retrieval SQL against a seeded 100k-chunk corpus. Regression threshold 20%. Catches an accidentally dropped index or a query plan flip.

### 9.2 Load tests (k6, pre-release, against staging)

| Scenario | Shape | Target |
| --- | --- | --- |
| Steady chat | 20 concurrent users, 10 min | p95 end-to-end ≤ 4 s, TTFT p95 ≤ 1.2 s |
| Search burst | 100 rps for 2 min | p95 retrieval ≤ 400 ms, no 5xx |
| Ingestion | 50 documents concurrently | No job failures, queue drains |
| Mixed | Chat + search + ingest simultaneously | No degradation beyond targets |
| Soak | 4 hours at 50% load | No memory growth, no connection-pool exhaustion |

### 9.3 Degradation drills

Each rung of the ladder in [architecture.md § 13.4](../context/architecture.md#134-degradation-ladder) has a test that kills the dependency and asserts the documented degraded behavior — not an error:

- Kill `inference` → lexical-only retrieval, banner shown
- Kill the reranker endpoint only → RRF order served, flagged
- Force an Anthropic 529 → falls back to `claude-sonnet-5`
- Force all generation to fail → extractive answer with citations
- Kill Postgres → 503 with `Retry-After`, no data corruption

## 10. E2E Tests

Playwright against the Compose stack. Three flows, kept small on purpose — E2E is the slowest and most brittle tier, so it covers journeys rather than details.

1. **Ask and cite** — log in, ask a question, watch it stream, click a citation, see the highlighted span in the source panel.
2. **Ingest and version** — upload a document, follow the job to completion, upload a modified version, see the supersession chain.
3. **Permission** — two users, same question, provably different answers.

Plus accessibility assertions on each: keyboard navigation reaches every control, the streaming region announces politely, focus is managed on panel open/close.

## 11. Test Data

| Kind | Location | Rule |
| --- | --- | --- |
| Unit fixtures | Inline or `tests/factories/` | Builder functions, not JSON blobs |
| Integration seed | `tests/fixtures/seed.py` | Two tenants, overlapping-looking content |
| Eval corpus | `evals/fixtures/` | Synthetic, bilingual, committed |
| Injection corpus | `evals/fixtures/injection/` | Adversarial documents |
| Cassettes | `tests/cassettes/` | Regenerated deliberately |

**No real customer data in any of them.** Enforced by a pattern test over the fixture directories.

## 12. CI Pipeline

```text
lint → typecheck → unit → integration → contract → security → eval-smoke → build → e2e
```

| Stage | Blocks merge | Notes |
| --- | --- | --- |
| lint / typecheck | Yes | `ruff`, `biome`, `mypy`, `tsc` |
| unit | Yes | |
| integration | Yes | testcontainers |
| contract | Yes | OpenAPI drift |
| **security** | Yes | Never skipped |
| eval-smoke | Yes | Regression gates |
| build | Yes | Images build and start |
| e2e | Yes | On PRs touching `apps/web` or `apps/api` |
| eval-full | No (reports) | Nightly; opens an issue on regression |
| load | No | Pre-release, manual |

## 13. Definition of Done (testing view)

Mirrors [conventions.md § 13](./conventions.md#13-definition-of-done), from the testing side:

- [ ] New logic has unit tests, including the failure paths
- [ ] New I/O has integration tests against real Postgres/Redis
- [ ] New endpoints have contract coverage and appear in the OpenAPI diff
- [ ] Anything touching tenancy or ACL has an explicit security test
- [ ] Anything touching retrieval or generation has an eval-smoke result attached
- [ ] Migrations exercised up **and** down
- [ ] No new `skip` or `xfail` without a linked task explaining it
- [ ] Evidence recorded in [test_evidence.md](../execution/test_evidence.md)
