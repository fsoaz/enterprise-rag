# Testing Standards

> **Applies to:** every contributor, human or AI.
> **Related:** [conventions.md](./conventions.md) · [api_rules.md](./api_rules.md) · [../context/architecture.md](../context/architecture.md) · [../execution/test_evidence.md](../execution/test_evidence.md)

A RAG system fails quietly. Retrieval gets slightly worse, an ACL filter is dropped, a citation stops resolving — nothing crashes, and nobody notices for a month. The test strategy is built around making quiet failures loud.

---

## 1. Test Tiers

| Tier | Scope | Runtime budget | Runs on |
| --- | --- | --- | --- |
| **Unit** | One function or class. No I/O, no network, no database. | < 30 s total | Every commit |
| **Frontend** | Vitest + Testing Library + jsdom. Components and browser-side modules in `apps/web`. | < 30 s | Every commit |
| **Integration** | Real Postgres and Redis in a disposable database. Real SQL, real migrations. | < 5 min | Every commit |
| **Contract** | Committed OpenAPI schema vs. implementation; generated TS types vs. schema | < 30 s | Every commit |
| **Security** *(deterministic)* | Tenant isolation, ACL correctness, log hygiene, tool authorization, injection **contract** tests with mocked model responses | < 2 min | Every commit — **never skipped** |
| **Adversarial** *(probabilistic)* | Live injection corpus against real models | ~10 min | Nightly and pre-release |
| **E2E** | Playwright against the full Compose stack | < 10 min | Pre-merge |
| **Eval** | Offline quality gates on the golden set | smoke < 5 min / full ~30 min | Smoke per PR, full nightly |
| **Load** | k6 against staging | ~15 min | Pre-release |

The table describes the target test strategy, including tiers not yet automated.
The current CI jobs run independently, without sequential `needs` dependencies.
See [§ 12](#12-ci-pipeline) for implemented jobs and remaining gaps.

## 2. Coverage

| Target | Threshold | Rationale |
| --- | --- | --- |
| `packages/retrieval` | 95% | ACL predicate construction is where a security bug hides |
| `packages/db` (ACL + tenancy) | 95% | Same |
| `packages/domain` | 90% | Pure logic, cheap to cover |
| `packages/llm` | 85% | Provider calls are mocked; the wrapper logic is testable |
| `packages/*` overall | 85% | |
| `apps/*` | 75% | Thin routers; the logic lives in packages |
| Whole repo | 75% | Target |

These Python coverage thresholds are targets; the current CI pytest commands do
not collect coverage or enforce them. Frontend coverage is enforced separately
by Vitest; see [§ 3.1](#31-frontend-tests).

Coverage is a floor, not a goal. A 95% number with no test for "user B cannot see user A's document" is worthless. Reviewers check what is tested, not how much.

## 3. Unit Tests

- Pure functions and classes with injected dependencies. If a test needs `unittest.mock.patch` to reach into a module's internals, the code has a design problem — fix the code.
- No `sleep`. No real clock — inject a time provider.
- No network, no filesystem outside `tmp_path`, no database.
- Parametrize aggressively; one assertion concept per test.
- Naming: `test_<unit>__<condition>__<expected>` — e.g. `test_acl_predicate__document_deny_overrides_collection_allow__excludes_document`.

**High-value unit targets:** RRF fusion math, ACL resolution order, chunk boundary logic, citation span mapping, groundedness verdict thresholds, cost computation from usage, staleness scoring, retry/backoff policy.

### 3.1 Frontend tests

`apps/web` runs Vitest with Testing Library and jsdom. `npm test` runs them;
`npm run test:coverage` adds the v8 report; CI runs the coverage form in the `web-test` job.

This tier exists because of a specific, repeated failure. Every frontend defect found in
the QA round — a CSP that left the page unhydrated, citation anchors that pointed at the
wrong sentence, an SSE parser that mishandled multi-line `data:` — passed `tsc`, `biome`
and `next build`, because **none of those loads a page** (R-070). A type checker cannot
observe behavior.

Rules for this tier:

- **Assert what the user sees, not what the component holds.** Query by role, label and
  text through Testing Library. A test that reaches for a class name or component internals
  re-breaks as soon as the markup is restyled, and never proves the control was reachable.
- **`fetch` is stubbed at the module boundary, not deep inside a component.** The
  component under test issues its real request path; the stub answers it.
- **The SSE parser is tested on fragmented input** — a frame split across chunks, and a
  malformed frame that must be dropped without taking the rest of the stream with it. It
  is the one module whose input arrives from the network in arbitrary pieces.
- **A locale test exercises the switch, not the dictionary.** A missing key is already a
  `tsc` failure by construction (`Record<Locale, Record<MessageKey, string>>`), so there is
  nothing for a test to add there; what a test can show is that switching locale updates
  the rendered strings *and* `document.documentElement.lang`.

The nine tests currently cover: the sign-in and signed-in states of `AuthGate`; SSE frame
splitting and malformed-frame recovery; the locale switch; the admin document list,
ingestion history and archive-without-reload; and on the chat page, that the `verifying`
stage is shown before any answer text is released, that citation anchors are unique and
sequential with invalid sentence bindings dropped, and that a follow-up turn sends bounded
conversation messages.

Coverage is reported, not gated: **72.31% statements, 58.58% branches, 78.26% functions**
at the time of writing, with the admin page the largest uncovered area. Per § 2 that number
is a floor, not a goal — this tier was added for the behaviors listed above, not for the
percentage.

## 4. Integration Tests

Real Postgres (with `pgvector`) and Redis. Migrations run against it, so the schema under test is the schema that ships.

**The target database is disposable, and the suite fails closed if it is not.** `make
test-integration` runs `scripts/run-integration-tests.sh`, which creates a database, applies
`init.sql`, migrates, seeds, runs `pytest -m integration`, and drops it on exit via a
`trap`. The helpers in `tests/integration_database.py` read `TEST_DATABASE_URL` and refuse
to run against anything else, so pointing the suite at a development database is an error
rather than a silent success.

Two guards sit in front of the destructive statements, because a `DROP DATABASE` built from
an environment variable is one typo away from deleting the wrong thing:

- The name must match `^[a-zA-Z0-9_]+$` — it is interpolated into SQL, so nothing else is
  acceptable.
- It must start with `test_` or end in `_test`. `enterprise_rag` cannot be named as the
  target no matter what is exported.

This replaced tests that wrote into the development database and left ACL rows behind
(R-071). The cost was measurable, not theoretical: while it lasted, no permission-slice
result measured locally was evidence, because the next run started from state the previous
run had polluted.

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

Everything in § 6.1–6.5 is **deterministic**: given the same code it produces the same verdict every run, so it is a legitimate per-commit merge gate. The probabilistic half — measuring whether a real model actually resists a real injection — lives in § 7.5 and runs nightly. Mixing the two would give a merge gate that fails on model variance and passes on luck.

### 6.0 Test the refused request, not the permitted one

**A security control is not covered until a test exercises the request that must fail.**

An access-control test that only asserts the happy path passes identically whether the control is enforced or entirely absent. This is not hypothetical: `require_role` was defined and never attached to any route for the whole first MVP pass, and every existing test still passed, because every existing test used a permitted caller (R-009).

Each control therefore needs a paired assertion:

| Control | Positive | **Negative (the one that matters)** |
| --- | --- | --- |
| Role gate | Steward uploads → 202 | Member uploads → **403** |
| Resource permission | Curator with `write` uploads → 202 | Curator without `write` on that collection → **403** |
| ACL on metadata reads | Owner lists the document | Non-grantee lists and **does not see it** |
| Service token | Correct token → 200 | Absent and wrong token → **401** |

The same rule covers the isolation tests below: "tenant A reads its own rows" proves nothing that "tenant A cannot read tenant B's rows" does not.

### 6.1 Tenant isolation

| Test | Assertion |
| --- | --- |
| Cross-tenant read | Tenant A's token cannot read any of tenant B's rows, on every tenant-scoped table |
| **RLS backstop** | The same test passes **with the ORM tenant filter deliberately removed**. This is the test that proves defense in depth is real rather than aspirational. |
| Raw SQL path | A hand-written query that forgets `tenant_id` is still blocked by RLS |
| Object storage | A content URL for tenant A's key cannot be produced or used under tenant B's context |
| Cache | No Redis key is reachable across tenants |
| Search results | An ANN query under tenant A never returns a tenant B chunk, including at high `ef_search` |
| **Worker payload tampering** | An ingestion task whose payload has been edited to name tenant B cannot read or write tenant B rows. The tenant context comes from the job row under `rag_app`, never from the payload — see [architecture.md § 4.2](../context/architecture.md#42-layer-2--postgres-row-level-security). |
| Role privilege | The connection used by ingestion has no `BYPASSRLS`; asserted against `pg_roles`, not assumed from configuration |

### 6.2 Access control

| Test | Assertion |
| --- | --- |
| Deny precedence | Document-level `deny` overrides collection-level `allow` |
| Default deny | A user with no matching ACL entry gets nothing |
| **Pre-filter proof** | A user permitted 5% of the corpus still receives a full top-8 — asserted by result count, which is what distinguishes pre-filtering from post-filtering |
| No count leakage | Result counts and pagination totals are identical whether inaccessible documents exist or not |
| Revocation | Removing an ACL entry takes effect on the **next** query. Asserted against the mechanism, not the outcome: the mutation and the `acl_version` bump commit in one transaction, and the version is re-read from Postgres per request. |
| Stale version rejected | An `acl_version` supplied from a token or a cached session is never used to key the predicate |
| Tool ACL | The `search_documents` tool runs under the caller's predicate, not a widened one |
| Citation ACL | A citation never resolves to a chunk the caller cannot read |
| Archived exclusion | An archived document is absent from new retrieval but its existing citations still resolve |
| Erasure tombstone | After erasure, `query_citations` rows survive with content nulled — a historical answer degrades to "source erased" rather than dangling |
| Legal hold | Erasure is refused with 409 while `legal_hold` is set |
| **Content-delivery revocation window** | Proxy mode: a revoked user is refused on the next byte range. Presigned mode: the test asserts the **documented** behavior — an already-issued URL remains usable until expiry — so the exposure stays visible rather than being quietly assumed away. See [api_rules.md § 13.1](./api_rules.md#131-presigned-urls-are-bearer-credentials). |

### 6.3 Prompt injection — contract tests only

Deterministic assertions about how the request is *constructed* and how a hostile response is *handled*. These use mocked model responses and run on every commit. Whether a live model actually resists an attack is measured separately in § 7.5.

| Test | Assertion |
| --- | --- |
| Structural placement | Retrieved content appears only in `document` blocks — never in `system`, never concatenated into user text. Asserted on the serialized request body. |
| Operator channel | Runtime instructions are sent as `role: "system"` messages, not as text inside a user turn |
| Tool allowlist | The request exposes only read-only tools, ACL-bound, within the call cap |
| Hostile-response handling | Given a mocked response attempting an unrequested tool call, the loop refuses it |
| Detection | Injection-shaped text is flagged at ingest and counted in `injection_flagged_total` — a pure heuristic test, no model involved |
| Egress scan | A mocked answer containing a secret pattern is blocked before leaving the API |

### 6.4 Log hygiene

Capture structured log output during an integration run and assert absence of: document content, chunk text, answer text, raw questions above `debug`, tokens, API keys, JWTs, and full email addresses.

### 6.5 Dependency & secret scanning

Dependency and secret scanning are required review practices, but `pip-audit`,
`npm audit`, and `gitleaks` are not configured in
[the repository CI workflow](../../.github/workflows/ci.yml). No tracked
pre-commit hook configuration supplies them either. Do not rely on CI to detect
secrets, dependency advisories, or undocumented environment variables.

Record actual scan commands, dates, results, and unresolved advisories when a
scan is performed. [VERIFY] External repository security settings and scanners
cannot be confirmed from the checked-in configuration.

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
| Cost per query | no rise > 20% | ≤ $0.03 median |

A gate breach fails the build. Overriding a gate requires an explicit note in the PR explaining why the new number is correct — and updating the baseline in the same commit, so the override is visible in history.

Injection success rate is deliberately **not** in this table — it is a probabilistic measurement and belongs in § 7.5.

### 7.3 Judge discipline

- Answer-quality judging uses `claude-haiku-4-5` with a **versioned rubric prompt**.
- The rubric prompt hash is stored on `eval_runs.judge_prompt_hash`.
- Comparing two runs with different judge hashes is flagged in the dashboard — a judge change must never be read as a quality change.
- Judge prompts live in `evals/harness/judges/` and change through the normal review process.

### 7.4 Baselines

Baseline metrics are committed to `evals/baselines/<git-sha>.json`. The smoke gate compares against the baseline of `main`. Updating a baseline is a deliberate, reviewed commit.

### 7.5 Adversarial evaluation (probabilistic)

The live half of injection testing: the corpus in `evals/fixtures/injection/` — instruction override, role confusion, fake system markers, encoded payloads, zero-width characters, instructions in table cells and image alt text, and a multi-document coordinated attempt — run against **real models**.

| Property | Value |
| --- | --- |
| Cadence | Nightly and pre-release |
| Gate | Success rate ≤ 1%, and no rise vs. the previous run |
| Merge-blocking | **No** |
| On breach | Opens an issue; blocks release, not merge |

**A probabilistic signal is never a per-commit merge gate.** The same commit can pass at 0.4% and fail at 1.2% on model variance alone, which would train the team to re-run CI until it goes green — the worst possible outcome for a security signal. Per-commit protection comes from the deterministic contract tests in § 6.3; this tier answers the different question of whether the defenses actually hold against a live model, and it answers it on a cadence where a real regression is investigated rather than retried.

Any successful injection is triaged as a `critical` finding regardless of the aggregate rate.

## 8. Determinism

| Tier | LLM handling |
| --- | --- |
| Unit | Fully mocked; fixed response objects |
| Integration | Recorded cassettes; no live calls |
| Contract | No LLM involved |
| Security (deterministic) | Fully mocked. No live call, by definition — that is what makes it a merge gate. |
| Adversarial (probabilistic) | **Live calls.** Nightly and pre-release only. |
| E2E | Cassettes by default; a live-mode flag exists for manual verification |
| **Eval** | **Live calls.** This is the only tier that spends money, and it is the point of the tier. |

Cassettes live in `tests/cassettes/` and are regenerated deliberately, never automatically. A stale cassette that hides a real API change is caught by the nightly eval run.

**The embedder is also a source of nondeterminism, and it is pinned the same way.** CI and
`make test-integration` set `INFERENCE_BACKEND=stub`, which returns SHA-256-derived unit
vectors and an identity rerank — same input, same vector, no weights to download, no GPU,
no model version drift between runs. Everything else defaults to `bge`
([architecture § 3.2](../context/architecture.md#32-inference-service-contract)).

The selection is explicit on both sides for a reason. `stub` must never be reachable by
accident in a deployment, and `bge` must never be reachable by accident in CI:

- `bge` raises at startup if the weights are unavailable rather than falling back, so a
  deployment cannot silently serve hash vectors.
- The stub reports `deterministic-hash-test-stub` as its model name, so any artifact it
  produced — a `chunk_embeddings` row, an eval report — is identifiable afterwards.
- **A number measured under `stub` is wiring evidence, never retrieval quality.** It says
  the services are connected and the SQL is right. It says nothing about whether the
  correct chunk was retrieved, and must not be quoted as if it did.

Other determinism rules: fixed random seeds; injected clock; no test depends on wall-clock ordering; no test depends on another test's side effects.

## 9. Performance Tests

Every performance number in this project is meaningless without the workload that produced it. A latency target can always be met by shrinking the corpus, dropping concurrency, or measuring a warm cache — so each target names a **profile** from [product.md § 7.4](../context/product.md#74-performance--cost) and is only comparable to another number from the same profile.

### 9.1 Micro-benchmarks (CI)

`pytest-benchmark` on retrieval SQL against the `dev-cpu` corpus (10k chunks, seeded, warm). Regression threshold 20%. Catches an accidentally dropped index or a query plan flip — it is a *relative* guard, not an SLO measurement.

### 9.2 Load tests (k6, pre-release, against staging)

Staging runs the **`cloud-gpu`** profile. Targets are read from the profile table rather than restated here, so the two cannot drift apart.

| Scenario | Shape | Target |
| --- | --- | --- |
| Steady chat | Profile concurrency (20 users), 10 min | `cloud-gpu` end-to-end verified-answer target; retrieving → generating → verifying status sequence |
| Search burst | 100 rps for 2 min | `cloud-gpu` retrieval-only target, no 5xx |
| Ingestion | 50 documents concurrently | Profile ingestion throughput; no job failures, queue drains |
| Mixed | Chat + search + ingest simultaneously | No degradation beyond profile targets |
| Soak | 4 hours at 50% load | No memory growth, no connection-pool exhaustion |
| Cold start | First request after deploy | Recorded, not gated — cold end-to-end latency is expected to exceed the warm target |

A load-test report that does not state its profile, corpus size, and warm/cold status is rejected in review.

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
| Integration database | Created and dropped per run | Name must end `_test` or start `test_`; never a long-lived database (§ 4) |

**No real customer data in any of them.** Enforced by a pattern test over the fixture directories.

**No tier reuses state across runs.** Unit and frontend tiers hold none; the integration
tier's database is created and dropped by the run that uses it. A test that passes only
because an earlier run left a row behind is not a passing test, and the failure mode is
silent in exactly the tests that matter most — an ACL check that succeeds against stale
grants (R-029, R-071).

## 12. CI Pipeline

```text
Implemented on main pushes and pull requests (independent jobs):
lint | typecheck (+ contract + Next build) | unit | web-test | integration-db | container-build

Evaluation workflows:
eval-smoke | scheduled eval-full | e2e | adversarial | pre-release load
```

| Stage | Job | Blocks merge | Notes |
| --- | --- | --- | --- |
| lint | `lint` | Yes | `ruff check`, `ruff format --check`, `biome check` |
| typecheck | `typecheck` | Yes | `mypy`, `import-linter`, `tsc`, `next build` |
| contract | `typecheck` | Yes | `make openapi-check`, then `cd apps/web && npm ci && npm run generate:api-types` followed by `git diff --exit-code src/lib/generated/api.ts` |
| unit | `unit` | Yes | `pytest -m 'not integration'` |
| **frontend** | `web-test` | Yes | `vitest run --coverage` |
| integration | `integration-db` | Yes | Postgres + Redis services, `enterprise_rag_test`, plus a real `inference` process on `INFERENCE_BACKEND=stub` |
| migrations | `integration-db` | Yes | `upgrade head` → `downgrade -1` → `upgrade head` → seed, from an empty database |
| **security** (deterministic) | `unit` / `integration-db` | Yes | Never skipped. Fully mocked — no live model call, which is what makes it a legitimate gate. |
| eval-smoke | `eval-smoke` | Yes | Pull requests; deterministic 48-item stub-inference run across all eight slices, compared with `evals/baselines/t407-smoke.json`. Hosted first-green evidence is pending for R-031. |
| build | `container-build` | See note below | Builds API/worker, inference, and web images; checks Compose configuration. `next build` also runs in `typecheck`. No image publishing or deployment. |
| e2e | — | — | Not wired |
| eval-full | `eval-full` | No (reports) | Scheduled full 320-item, eight-slice run with four configured strategies; retains the report and makes no paid model calls. |
| **adversarial** (probabilistic) | — | **No** | Nightly and pre-release. Blocks **release**, not merge — see § 7.5. Not wired |
| load | — | No | Pre-release, manual |

Rows without a job do not exist. They remain in the table when they describe an intentional
future gap, such as e2e, adversarial, or load testing. The evaluation rows above are now
wired; their hosted execution evidence is tracked in [T-407](../tasks/T-407-ci-evaluation-gates.md)
and [E-012](../execution/test_evidence.md).

“Blocks merge” is the intended repository policy. [VERIFY] Actual required status
checks depend on hosted branch-protection settings, which are not in this repository.

**Two changes closed the failures recorded against this job.** `integration-db` now starts
a real `inference` process and waits on `/ready` before the suite runs, which resolves the
dependency `test_feedback_rejects_another_users_query` acquired through fixture setup
(R-059) — the fix was to provide the contract the test actually needed, not to weaken the
test. And the job's database is `enterprise_rag_test`, driven by `TEST_DATABASE_URL`, so
the suite no longer has a name it could use to reach a development database (R-071).

The migration steps run against a database created empty in the same job. That ordering is
deliberate: `0001_initial` derives its schema from current model metadata, so a migration
that conflicts with a from-scratch build is invisible to any check that only moves an
existing database forward (R-058). `make migrate-check` reproduces this locally.

An integration test may depend on real services needed by the behavior it claims to
cover. It must not acquire an unrelated dependency through fixture setup: feedback
authorization needs a query row, not a successful chat/retrieval/inference round
trip. Conversely, a test that claims to cover chat must provide or explicitly mock
the inference contract and must exercise the unavailable-inference behavior.

Async clients, engines, and pools belong to the event loop that created them.
`TestClient` portal loops and ad-hoc `asyncio.run()` calls must not share cached async
resources; creation, use, reset, and disposal happen on one owning loop
([R-061](../execution/review_notes.md)).

## 13. Definition of Done (testing view)

Mirrors [conventions.md § 13](./conventions.md#13-definition-of-done), from the testing side:

- [ ] New logic has unit tests, including the failure paths
- [ ] New I/O has integration tests against real Postgres/Redis
- [ ] New endpoints have contract coverage and appear in the OpenAPI diff
- [ ] Anything touching tenancy or ACL has an explicit security test
- [ ] Anything touching retrieval or generation has an eval-smoke result attached
- [ ] Migrations exercised up **and** down
- [ ] No new `skip` or `xfail` without a linked task explaining it
- [ ] Every new access control has a **negative** test — the request that must be refused (§ 6.0)
- [ ] A conditional skip distinguishes *absent* from *misconfigured*: a dependency that is reachable but rejecting must fail, not skip
- [ ] Evidence records the skip count and the environment, not just the pass count
- [ ] Tests do not depend on row order or accumulated state in a long-lived dev database
- [ ] Evidence recorded in [test_evidence.md](../execution/test_evidence.md)
