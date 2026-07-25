# Review Notes

> Register of review findings — self-review, peer review, `/code-review`, `/security-review`, and anything spotted in passing.
> **Related:** [work_log.md](./work_log.md) · [test_evidence.md](./test_evidence.md) · [../standards/testing.md](../standards/testing.md)

A finding outside the current task's scope goes **here**, not into the current PR. That is the mechanism that keeps PRs single-purpose without losing the observation.

---

## Severity

| Level | Meaning | Handling |
| --- | --- | --- |
| `critical` | Security hole, data loss, or cross-tenant leakage | Stop other work. Fix now. |
| `high` | Incorrect behavior in a core path, or a missing security test | Fix before the phase closes |
| `medium` | Real defect in a non-core path, or a design smell that will cost later | Scheduled into a task |
| `low` | Cleanup, clarity, minor inefficiency | Fix opportunistically |
| `info` | Observation, not a defect | Recorded for context |

## Status

`open` → `scheduled` (task ID assigned) → `resolved` (fixed and verified) · `wont-fix` (with a reason) · `duplicate` (of another ID)

---

## Register

| ID | Date | Source | Severity | Location | Finding | Status | Resolution |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R-001 | 2026-07-25 | architecture review | `critical` | `api_rules.md` endpoint inventory | `DELETE /documents/{id}` ("remove document and all versions") contradicts resolvable historical citations, the append-only version chain, and 90-day query retention. A cascade delete strands every prior answer that cited the document. | resolved | Replaced with archival (default, reversible) + privileged erasure that retains tombstones and nulled citations. `DELETE` now returns 405. [architecture § 6.4](../context/architecture.md#64-removal-archival-not-deletion) |
| R-002 | 2026-07-25 | architecture review | `high` | `architecture.md § 4.2` | "Migrations and the Celery worker's system-level sweeps use a separate privileged role" conflates DDL with tenant-document ingestion. Ingestion processes tenant-controlled content and must not hold an unrestricted connection. | resolved | Three roles: `rag_migrate` (DDL, `BYPASSRLS`), `rag_app` (API **and ingestion**, RLS applies), `rag_maint` (enumerate only). Tenant context comes from the job row, never the task payload. |
| R-003 | 2026-07-25 | architecture review | `high` | `api_rules.md § 13` | Claimed signed content URLs are "scoped to the requesting user." **Factually wrong** — S3 presigned URLs are bearer credentials usable by anyone holding the string until expiry. | resolved | Proxied download is now the default. Presigning is an opt-in path described accurately, with the revocation window stated. [api_rules § 13.1](../standards/api_rules.md#131-presigned-urls-are-bearer-credentials) |
| R-004 | 2026-07-25 | architecture review | `high` | `roadmap.md` | v1 boundary spans six formats, OCR, three UIs, budgets, Terraform, and the full degradation ladder — a multi-quarter product. High risk of never reaching a deployable release. | resolved | Split into Milestone A (portfolio release, all six differentiators, Compose) and Milestone B (breadth). Two items pulled back into A against the reviewer's cut: document-level deny overrides and `cost_ledger`. |
| R-005 | 2026-07-25 | architecture review | `medium` | `architecture.md § 5.3` | Degrading to a materialized `user_visible_documents` table creates a **second authorization system** — security-critical derived state that can be stale, partial, or silently failed. Specified before any benchmark justified it. | resolved | Removed entirely. Direct ACL query is the only implementation; recorded as [ADR-008](../context/architecture.md#adr-008--no-materialized-authorization-state) with fail-closed conditions if a benchmark ever forces it. |
| R-006 | 2026-07-25 | architecture review | `medium` | `architecture.md § 5.3` | "Immediate revocation" via `acl_version` was asserted without specifying where the version is read or whether the bump is atomic with the ACL write. | resolved | Mechanism specified: mutation and increment commit in one transaction; version re-read from Postgres per request; never from cache, JWT, or session. |
| R-007 | 2026-07-25 | architecture review | `medium` | `product.md § 7.4` | SLOs (p95 TTFT ≤ 1.2 s, e2e ≤ 4 s) fix no workload — corpus size, concurrency, CPU vs GPU, warm vs cold, model. A passing measurement could come from an artificially easy run. | resolved | Two normative profiles, `dev-cpu` and `cloud-gpu`, each fixing nine parameters. Every target names one. CPU numbers relaxed to what the reranker actually permits. |
| R-008 | 2026-07-25 | architecture review | `medium` | `testing.md § 6.3` | The prompt-injection suite sat in the per-commit tier that is "never skipped," but injection outcomes are probabilistic. A merge gate on model variance is either flaky or meaningless. | resolved | Split: deterministic injection **contract** tests (mocked responses) stay per-commit; the live corpus moves to a nightly adversarial tier that blocks release, not merge. |

### Milestone A code review — 2026-07-25

Source: implementation review of the Milestone A MVP branch. R-009 through R-029 were fixed in the same pass; R-030 and R-031 are open.

| ID | Date | Source | Severity | Location | Finding | Status | Resolution |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R-009 | 2026-07-25 | code review | `critical` | `apps/api/src/api/routers/acl.py:45` | `require_role` was defined in `deps/auth.py` and **never called**. No endpoint had a role check. Any authenticated user — including `viewer` — could `POST /acl/entries` granting themselves `read` on any collection or document in the tenant: a complete ACL bypass. | resolved | `CuratorUser` (admin/steward) on upload, archive, unarchive, collection create; `AclAdminUser` (admin) on both `/acl/entries` routes. Regression test asserts member upload → 403. |
| R-010 | 2026-07-25 | code review | `high` | `.env.example`, `infra/compose/docker-compose.yml` | `.env.example` shipped `DEV_AUTH_BYPASS=true` and the README instructs `cp .env.example .env`; the compose `api`/`worker` services loaded that same file via `env_file`. The documented setup path produced a stack where `X-Dev-User: <anything>` is full impersonation. | resolved | `.env.example` ships `false` with a danger comment. Compose sets `DEV_AUTH_BYPASS: "true"` inline so the blast radius is the demo stack only. README documents the risk at the point of use. |
| R-011 | 2026-07-25 | code review | `high` | `apps/api/src/api/routers/documents.py:150,189` | `/documents` list, detail, and jobs filtered on `tenant_id` only. `/search` applied `document_acl_predicate`; the documents API did not. Every tenant member could enumerate all document titles and collection membership regardless of ACL. | resolved | `_readable_documents()` applies `resolve_acl` + `document_acl_predicate` to list, detail, jobs, archive, and unarchive. |
| R-012 | 2026-07-25 | code review | `high` | `apps/inference/src/inference/main.py` | Callers sent `Authorization: Bearer $INFERENCE_SERVICE_TOKEN` (`retrieval/dense.py`, `worker/pipeline/embed.py`) and the service discarded it. The config implied a trust boundary that did not exist. | resolved | `inference/deps.py` enforces the token with `hmac.compare_digest`; open with a startup warning when unset so bare local runs still work. Compose and `.env.example` set it. |
| R-013 | 2026-07-25 | code review | `high` | `apps/api/src/api/routers/documents.py` | Found while verifying R-009: holding a curator role granted upload into **any** collection in the tenant. A steward scoped to one collection could inject documents into another, including one they could not read back. | resolved | Upload additionally requires ACL `write` on the target collection (admin bypasses). Surfaced by an integration test where a steward uploaded into a collection they could not then read. |
| R-014 | 2026-07-25 | code review | `high` | `packages/retrieval/src/retrieval/acl.py:44` | `load_subject_set` used `session.scalar(select(RoleAssignment.role)…)`, taking one arbitrary row. A user with multiple roles could silently lose `admin`, changing ACL resolution non-deterministically. | resolved | `scalars().all()` — all roles load. |
| R-015 | 2026-07-25 | code review | `high` | `apps/inference/src/inference/routers/embed.py` | The embedding stub returned all-zero vectors. pgvector's `<=>` is undefined against a zero vector and yields **NaN**, so `1.0 - distance` produced NaN scores that propagated through ordering, RRF fusion, and `retrieval_confidence`. Dense retrieval was not "stubbed", it was producing garbage. | resolved | Deterministic SHA-256-derived **unit** vectors, query and passage sharing one encoding. Tests assert non-zero, unit norm, and determinism. |
| R-016 | 2026-07-25 | code review | `medium` | `apps/inference/src/inference/routers/rerank.py` | The rerank stub scored candidates by `len(doc)`. Because `hybrid_rerank` was the default strategy for `/search` and `/chat`, default retrieval reordered fused results longest-first — strictly worse than the RRF order it was handed. | resolved | Identity pass-through with monotonically decreasing scores; default strategy moved to `hybrid_rrf` until real cross-encoder weights land (T-206). See [ADR-009](../context/architecture.md#adr-009--a-stub-degrades-to-a-no-op-never-to-a-wrong-signal). |
| R-017 | 2026-07-25 | code review | `high` | `apps/api/src/api/services/chat.py:180` | In the live-LLM streaming path, tokens were forwarded as they arrived, the groundedness verdict was computed afterwards, and on abstention the replacement text was emitted as *another* `token` event. The web client concatenates, so the user read the full ungrounded answer followed by "I could not find support." The abstention gate was cosmetic whenever streaming and a real API key were both active. | resolved | The model stream is consumed but not forwarded; the answer is emitted from a single point after the verdict exists, chunked so the SSE contract is unchanged. |
| R-018 | 2026-07-25 | code review | `high` | `evals/harness/run.py:22` | `rows = [(item.gold_chunk_ids, item.gold_chunk_ids) …]` — the retrieved list *was* the gold list, so `recall@10`, `nDCG@10`, and `MRR@10` were 1.0 by construction. `retrieve()` was never called. "Phase 4: metrics harness" measured nothing. | resolved | Rebuilt against a real corpus: `evals/corpus.json` manifest, `evals/harness/corpus.py` ingests fixtures through the real worker pipeline, `run.py` calls `retrieve()` per item as the item's `acting_user` and exits 2 rather than printing synthetic numbers. First real figures in [test_evidence.md](./test_evidence.md). |
| R-019 | 2026-07-25 | code review | `medium` | `apps/api/src/api/deps/auth.py:162` | The OIDC path took `roles`/`groups` from token claims while `resolve_acl` read `role_assignments` from the database. `require_role` and retrieval could disagree about the same caller. | resolved | Authorization always reads the database. Claims are still required (a malformed token is rejected early) but are not trusted for access decisions. |
| R-020 | 2026-07-25 | code review | `medium` | `apps/api/src/api/routers/documents.py:87` | `await file.read()` buffered an unbounded body into memory before any size check. The `upload-too-large` (413) and `unsupported-media-type` (415) problem slugs were defined in `problem.py` and never raised, despite the stated PDF/MD/TXT scope. | resolved | `_read_capped()` streams and aborts past `MAX_UPLOAD_BYTES` (25 MB default) → 413. MIME allowlist → 415, with extension preferred over the browser's generic `application/octet-stream`. |
| R-021 | 2026-07-25 | code review | `medium` | `apps/api/src/api/services/ingest.py:49` | Synchronous boto3 calls ran directly in async handlers, and `INGEST_SYNC=true` blocked the event loop on `future.result()` for the entire parse/embed cycle — stalling every other in-flight request. | resolved | Both moved to `anyio.to_thread.run_sync`; `enqueue_ingest` is now async. The Celery `.delay()` publish is also threaded (kombu blocks on a stalled broker). |
| R-022 | 2026-07-25 | code review | `medium` | `apps/api/src/api/routers/documents.py:105` | The object was written to S3 before the DB commit, so any commit failure stranded an unreferenced object in the bucket. | resolved | Order inverted: commit, then upload. An upload failure marks the job and version `failed`, leaving a visible, cleanable record instead of invisible orphan bytes. |
| R-023 | 2026-07-25 | code review | `low` | `apps/api/src/api/services/chat.py:125` | Bare `assert generation is not None` on a production path — stripped entirely under `python -O`. | resolved | Replaced with an explicit extractive fallback for the "stream ended without a terminal event" case. |
| R-024 | 2026-07-25 | code review | `medium` | `packages/llm/src/llm/client.py:107` | `max_tokens=4096` with adaptive thinking at `effort: "high"`. On the primary model `max_tokens` caps thinking **plus** response text, so long answers risked mid-sentence truncation. | resolved | `MAX_TOKENS_NONSTREAMING = 16_000`, `MAX_TOKENS_STREAMING = 64_000`, named constants with the reason recorded at the definition. |
| R-025 | 2026-07-25 | code review | `low` | `packages/llm/src/llm/client.py:98` | `@retry(stop_after_attempt(3))` with no exception predicate retried deterministic 400s three times, burning latency and quota for an identical failure. | resolved | `retry_if_exception_type` scoped to `APIConnectionError`, `APITimeoutError`, `RateLimitError`, `InternalServerError`. |
| R-026 | 2026-07-25 | code review | `low` | `apps/worker/src/worker/pipeline/index.py:42` | FTS `search_vector` was written with one `UPDATE` per chunk — a round trip per chunk on every ingest. | resolved | Batched with an expanding `IN` bind, 500 chunks per statement. |
| R-027 | 2026-07-25 | code review | `medium` | `infra/compose/docker-compose.yml` | The `api` and `worker` services overrode `DATABASE_URL` but not `DATABASE_URL_MIGRATE`, so `Settings.async_identity_url()` — the BYPASSRLS connection used to resolve identity before the tenant GUC is set — pointed at `localhost:15432` from inside the container. | resolved | `DATABASE_URL_MIGRATE` and `DATABASE_URL_MAINT` overridden for both services. |
| R-028 | 2026-07-25 | code review | `medium` | `docs/execution/test_evidence.md` | Evidence recorded "`make test` → 35 passed". The real figure was 32 passed **+ 3 skipped**: without `DATABASE_URL`, MinIO, and inference reachable, the chat and both RLS isolation tests skip silently. "RLS isolation tests green" was unsupported locally — those tests had not run. | resolved | Evidence records both configurations and flags that an unqualified pass count is meaningless. With the environment loaded: **39 passed, 0 skipped**. `_inference_reachable` now raises on a 401 instead of converting a misconfiguration into a silent skip. |
| R-029 | 2026-07-25 | code review | `medium` | `apps/api/tests/test_ingest_search.py` | Tests took `collections[0]` and used fixed content markers. Both are order- and state-dependent against a dev database that accumulates rows: adding an alphabetically-earlier collection silently redirected uploads into a differently-ACL'd collection, and stale documents matched the fixed marker. | resolved | Collections resolved by name; markers are `uuid4`-unique per run. Two stale documents left in `Acme Legal` by the failing runs were deleted from the local dev database. |
| R-030 | 2026-07-25 | code review | `medium` | `packages/retrieval/src/retrieval/dense.py:61`, `lexical.py:68` | Retrieval hard-codes `effective_to IS NULL` and has no point-in-time filter. The `as_of` field in `evals/datasets/versioned.jsonl` is parsed and ignored, so as-of-date questions cannot be answered. Now visible: the `versioned` slice scores `recall@10 = 0.50`, with `ver-002` failing. | open | Needs an `as_of` parameter threaded from `/search` and `/chat` through `retrieve()` into both arms' version predicates. Not scheduled. |
| R-031 | 2026-07-25 | code review | `low` | `.github/workflows/ci.yml` | The eval harness is not wired into CI. The `integration-db` job runs Postgres but no inference service, so `--load-corpus` cannot embed. Phase 4's "smoke subset per PR with regression gates" exit criterion is unmet. | open | Requires standing up `inference` as a CI service (or a recorded-vector fixture mode). Not scheduled. |

<!--
Row format:
| R-001 | 2026-08-03 | self | high | packages/retrieval/fusion.py:52 | RRF applied after the ACL filter instead of inside the CTE | scheduled | T-211 |
-->

---

## Standing Review Checklist

Applied to every PR, in addition to whatever the diff itself suggests. Ordered by blast radius.

### Tenancy & access control

- [ ] Every new table has `tenant_id NOT NULL` **and** an RLS policy
- [ ] `tenant_id` is derived from the JWT, never from a request parameter or body
- [ ] Every new query is tenant-scoped, and would still be safe if the ORM filter were removed
- [ ] ACL is applied **inside** the retrieval predicate, never as a post-filter
- [ ] A new endpoint returning a resource the caller cannot see returns 404, not 403, where existence is secret
- [ ] ACL cache invalidation still triggers on `acl_version` bump
- [ ] Every role or permission dependency is **attached to a route**, not merely defined — grep for the dependency name and confirm a call site *(R-009)*
- [ ] A write endpoint checks permission on the **target** resource, not just the caller's role *(R-013)*
- [ ] Metadata-listing endpoints apply the same ACL predicate as `/search` — titles and collection membership are not free *(R-011)*
- [ ] Authorization facts come from the database, never from a token claim *(R-019)*
- [ ] Any auth-bypass switch defaults to **off** in committed config, and is enabled only where the blast radius is stated *(R-010)*

### Retrieval & generation

- [ ] Retrieved content appears only in `document` content blocks — never in `system`, never concatenated into user text
- [ ] Every answer path produces resolvable citations, or downgrades the groundedness verdict
- [ ] `stop_reason` is checked before `content` is read
- [ ] Embedding calls use the correct `query` vs. `passage` mode
- [ ] A changed prompt has an eval-smoke run attached to the PR
- [ ] Nothing volatile was introduced into the cached prompt prefix
- [ ] No answer text reaches the client before the groundedness verdict exists *(R-017)*
- [ ] A stub degrades to a **no-op**, never to a fabricated ranking or a value the maths cannot handle *(R-015, R-016)*
- [ ] `max_tokens` leaves headroom for thinking as well as response text *(R-024)*
- [ ] Retries are scoped to transient exception types, not bare attempt counts *(R-025)*

### Cost & operations

- [ ] Every new LLM call writes a `cost_ledger` row
- [ ] Prices come from the versioned table, not a constant
- [ ] New external calls have a timeout, a retry policy, and a documented degraded mode
- [ ] New metrics and log fields carry `tenant_id` and `request_id`

### Removal & retention

- [ ] No new endpoint hard-deletes content that a `query_citations` row may reference *(R-001)*
- [ ] Erasure paths retain the tombstone, the nulled citation, and the `erasure_log` entry
- [ ] `legal_hold` is honored before any purge

### Data & migrations

- [ ] Migration is reversible and `downgrade()` was exercised
- [ ] Breaking schema changes follow expand/contract
- [ ] No merged migration was edited
- [ ] Backfills are batched and idempotent

### Hygiene

- [ ] No document content, question text above `debug`, credential, or full email address in logs
- [ ] No secret in the diff; `gitleaks` clean
- [ ] `.env.example` updated for new configuration
- [ ] `openapi.json` regenerated and committed if the surface changed
- [ ] No new `skip`/`xfail` without a linked task
- [ ] A conditional skip fails loudly on **misconfiguration** and skips only on genuine absence *(R-028)*
- [ ] Recorded pass counts state how many tests skipped and why — "N passed" alone is not evidence *(R-028)*
- [ ] An eval metric is computed from a real pipeline call, never from the expected value *(R-018)*
- [ ] Tests do not depend on row order or accumulated state in a long-lived dev database *(R-029)*
- [ ] Comments explain why, not what; no restated-code comments
- [ ] No abstraction added for a hypothetical second caller

### Documentation

- [ ] Behavior change reflected in `docs/context/`
- [ ] Architectural decision recorded as an ADR
- [ ] Task file's acceptance criteria all actually checked, not assumed

---

## Recurring Themes

> Patterns that show up across multiple findings. When a theme appears three times, it becomes a lint rule, a test, or a checklist item — a repeated human catch is a missing automation.

**Unverifiable claims** *(R-003, R-006, R-007)* — three of the first eight findings were assertions the document made without stating a mechanism: "scoped to the requesting user", "revocation is immediate", "p95 ≤ 1.2 s". Each was plausible and none was checkable, and one turned out to be false. Now a checklist item: **a security or performance guarantee must state the mechanism or the workload that makes it true, or it does not go in the document.**

**Premature security infrastructure** *(R-002, R-005)* — both involved building a second, more privileged path before anything required it. Prefer the constrained path until a benchmark forces otherwise, and make the escape hatch fail closed.

**Defined but never wired** *(R-009, R-012, R-020)* — three findings where the capability existed in the codebase and was never reached at runtime: `require_role` had no call site, `INFERENCE_SERVICE_TOKEN` was sent and discarded, and the 413/415 problem slugs were declared and never raised. Each read as "implemented" to anyone grepping for the identifier. **Third occurrence, so it becomes a rule:** a security control is not done until a test exercises the *negative* path — the request that must be refused. Now a checklist item under Tenancy & access control.

**Fabricating instead of abstaining** *(R-015, R-016, R-018)* — a stub returning zero vectors, a stub inventing a length-based ranking, and an eval scoring gold against gold. All three produced confident, plausible, wrong output where "no signal" was the honest answer, and all three were invisible precisely because nothing failed. The rule that follows: **a placeholder degrades to a no-op and says so; it never manufactures a value the downstream maths will treat as real.** Recorded as [ADR-009](../context/architecture.md#adr-009--a-stub-degrades-to-a-no-op-never-to-a-wrong-signal).

**Evidence that overstates** *(R-018, R-028)* — "35 passed" counted skips as passes, "RLS isolation tests green" described tests that had not run, and the eval harness reported 1.0 on metrics it never computed. Related to the earlier *unverifiable claims* theme but distinct: these were not unfalsifiable assertions, they were measurements of the wrong thing. **A number in the evidence log states what was measured, under what environment, and what did not run.**
