# Work Log

> Append-only, reverse chronological — newest entry at the top, directly under this header.
> One entry per completed task. Never edit or delete a past entry; correct it with a new one that says what changed.
> **Related:** [current_task.md](./current_task.md) · [test_evidence.md](./test_evidence.md) · [review_notes.md](./review_notes.md)

## Entry format

```markdown
## YYYY-MM-DD — T-XXX — <title>

**Status:** done | partial | abandoned
**PR:** <link>
**Branch:** <branch>

### What changed
<Two or three sentences. The outcome, not the diff.>

### Files touched
- `path` — what and why

### Decisions
<Non-obvious choices and the reasoning. If it is architectural, it also became an ADR.>

### Deviations from the task file
<What differed from plan and why. "None" is a valid answer.>

### Verification
<What was run and what it showed. Link the test_evidence.md entry.>

### Follow-ups
<Task IDs or review_notes IDs raised. "None" is valid.>
```

---

## 2026-07-29 — Full-system QA review and remediation (R-078 → R-098)

**Status:** done
**PR:** —
**Branch:** `main` (uncommitted working tree)

### What changed

A full-system QA review at `5b26159`, commissioned as **static evidence only** — no services were started — followed by five remediation and verification rounds. Twenty findings; nineteen fixed and verified, one (`R-083`, untracked `docs/`) accepted as `wont-fix`. One regression introduced during remediation (`R-098`) was caught and closed.

The three that mattered most:

- **`R-080`** — the injection scorer deleted ordinary policy prose from the corpus. *"Employees must not jailbreak or root company-issued mobile devices"* scored 0.95, and both retrieval arms filter at 0.8, so the documents most likely to use the vocabulary were the documents the system could not answer about. Ingest reported success either way.
- **`R-081`** — `unrelated` entailment labels, documented as the conservative default when the judge cannot match a claim, were read by nothing. An all-`unrelated` set returned `grounded`.
- **`R-082`** — erasure never touched `queries`, so erased document text survived verbatim in `answer_text` on the degraded path, in the one code path whose docstring promises it will not.

### Files touched

`apps/worker/src/worker/pipeline/chunk.py` · `packages/domain/src/domain/types.py` · `packages/domain/src/domain/embeddings.py` *(new)* · `packages/llm/src/llm/{client,groundedness}.py` · `packages/retrieval/src/retrieval/{dense,pipeline}.py` · `apps/api/src/api/{main,settings}.py` · `apps/api/src/api/routers/{admin,documents}.py` · `packages/db/src/db/models.py` · `packages/db/migrations/versions/0004_erasure_audit.py` *(new)* · `apps/web/src/lib/same-origin.ts` *(new)* · `apps/web/src/{app,components,lib}/…` · `infra/compose/docker-compose.yml` · `Makefile` · `pyproject.toml` · `.env.example` · `apps/web/.env.example` *(new, previously untracked)* · `README.md` · tests in `apps/api/tests/test_erase_redaction.py` *(new)*, `packages/domain/tests/test_embeddings.py` *(new)*, `apps/web/src/app/api/auth/logout/route.test.ts` *(new)*, `apps/worker/tests/test_chunk.py`, `packages/llm/tests/test_groundedness.py`

### Decisions

| Decision | Why |
| --- | --- |
| Separate the injection **hard-block** band from the **flag** band rather than narrow an exemption | Two attempts at exemption-tuning failed in opposite directions and neither converged. One threshold was answering two unrelated questions — what a document may say, and what the model may be told. `INJECTION_RISK_LINGUISTIC` (0.75) splits them; detection sensitivity is unchanged, only the response to a linguistic hit. [ADR-011 amendment](../context/architecture.md#adr-011--a-signal-that-nothing-reads-is-not-a-control) |
| Redact `queries.answer_text` inside the erasure transaction, before `delete(Chunk)` | `query_citations` cascade off `chunks.id`, so the citation lookup returns empty if the delete runs first and redaction silently degrades to the overlap path alone. Constraint stated in the helper's docstring and pinned by a test proven to fail under the inverted order |
| Catch affected queries by **two** paths — citation rows and `retrieved_chunk_ids &&` overlap | The overlap path is what covers an abstention: retrieval happened, the answer was built from chunks, and no citation row was ever written |
| Retain `queries.question` under erasure | It is the user's own input, not the erased document's text. Erasing it would destroy the audit trail the erasure log exists to provide |
| Derive `EMBEDDING_MODEL_VERSION` from `INFERENCE_BACKEND`, ignoring a stale `stub-v0` override | The primary key is `(chunk_id, model_name, model_version)`. Two backends sharing a version label do not collide loudly — they collide silently, ranking real query vectors against hash-derived passage vectors |
| Do not register the CORS middleware at all when the origin list is empty | An unregistered middleware cannot be misconfigured into permissiveness; a registered one with an empty list is one edit away from it |

### Deviations from the task file

No task file — this was a review round, not a scheduled task. Every finding is registered in [review_notes.md](./review_notes.md) as `R-078` → `R-098` per the convention that an out-of-scope observation goes to the register rather than into the current PR.

### Verification

[E-009](./test_evidence.md) — final gate: ruff, 5/5 import contracts, **80 passed / 1 skipped / 14 deselected**, OpenAPI in sync, Biome across 25 files, `tsc`, **11 frontend tests**. Per-round verification, including the two rejected fixes for `R-080`, is in [qa_report_2026-07-29.md § 9–13](./qa_report_2026-07-29.md).

Three verification habits earned their place this round and are worth repeating:

1. **The gate passed at `5b26159` with all twenty findings present.** Lint, typecheck and both test suites were green before the review started. Whatever a green gate is evidence of, it is not evidence that the system does what it claims.
2. **Two fixes were rejected on evidence, both with a green suite.** Each had been tuned to the exact strings the review published rather than to the class those strings illustrated. Assertions now name thresholds (`INJECTION_RISK_FLAG <= score < INJECTION_RISK_BLOCK`) so the suite sees a banding regression rather than a wording one.
3. **The ordering pin was accepted only after the code was broken on purpose** and the test was observed to fail. An ordering assertion that has never been seen to fail is not evidence that the ordering is enforced.

### Follow-ups

| Item | Where |
| --- | --- |
| Existing `stub-v0` corpora are invisible under `bge` and need re-ingest — correct fail-closed behaviour, but no reindex task exists to perform it | `R-086`; roadmap, alongside the missing worker task |
| Measure the `[UNTRUSTED]` **label rate** alongside exclusion rate — the flag band is now broad, and whether it is informative or merely loud is an empirical question | qa_report § R3-4 |
| Give the two sentence splitters a shared fixture before they drift; they are verified equivalent today by hand only | `R-090` |
| Answer quality, latency and cost against the live Anthropic API remain unmeasured, and the eval harness is still a local command rather than a CI gate | `R-031` (open) |

---

## 2026-07-27 — Milestone A closing round — auth, real weights, isolation, pagination

**Status:** done
**PR:** —
**Branch:** `main` (uncommitted working tree)

### What changed

Closed the eleven QA findings that were still open or partial after the 2026-07-26 round: `IS-03`, `IS-07`, `IS-08`, `IS-09`, `IS-11`, `IS-12`, `IS-20`, `IS-21`, `IS-23`, `IS-24`, `IS-32`. The frontend now has real OIDC sign-in, the inference service runs real BGE-M3 and BGE-reranker-v2-m3 weights, integration tests run against a disposable database, and every listing paginates by keyset. Milestone A's exit criteria are met apart from the answer-quality columns, which need production Anthropic credentials.

Work was ordered by dependency, not by finding number: authentication first (nothing else is demonstrable without a way to sign in), then the two things that make results trustworthy — deterministic inference selection and database isolation — then the features that build on them.

### Files touched

- `apps/web/src/lib/auth/server.ts` — `server-only` OIDC helper: metadata discovery, PKCE, `state` comparison via `timingSafeEqual`, refresh rotation
- `apps/web/src/app/api/auth/{login,callback,session,logout}/route.ts` — the browser-facing half of the flow
- `apps/web/src/app/api/backend/[...path]/route.ts` — authenticated proxy; buffers the body once so a request can be retried after a refresh
- `apps/web/src/components/auth-gate.tsx` — signed-in/signed-out states
- `infra/compose/keycloak/enterprise-rag-realm.json` — realm sharing the seed's tenant UUIDs
- `apps/inference/src/inference/backend.py` — `bge` | `stub` selection; raises at startup rather than degrading
- `apps/api/src/api/pagination.py` — opaque keyset cursors
- `packages/db/migrations/versions/0003_keyset_pagination_indexes.py` — six composite indexes matching each `ORDER BY`
- `apps/api/src/api/routers/chat.py` — `messages` alongside `question`, bounds validated on the request model
- `apps/web/src/lib/i18n.tsx` — typed EN/PT dictionaries, locale context, cookie
- `apps/web/vitest.config.ts`, `src/test/`, `*.test.tsx` — frontend test tier
- `scripts/run-integration-tests.sh`, `tests/integration_database.py` — disposable database with two guards on the name
- `.github/workflows/ci.yml` — `web-test` job; OpenAPI and generated-types drift checks; `integration-db` gets an inference process and `enterprise_rag_test`
- `openapi.json`, `apps/web/openapi.json`, `apps/web/src/lib/generated/api.ts` — regenerated

### Decisions

Two became ADRs:

| Decision | Rationale in short |
| --- | --- |
| [ADR-013](../context/architecture.md#adr-013--the-browser-never-holds-a-token) — the browser never holds a token | A public SPA holding tokens makes every XSS a credential leak. Next.js server routes run the exchange and proxy with the bearer attached, so there is nothing in the page to steal |
| [ADR-014](../context/architecture.md#adr-014--pagination-cursors-encode-a-position-not-an-offset) — cursors encode a position | `OFFSET` was the smaller change and is wrong here: rows arrive continuously from ingest, so an insert before the current page silently shifts every later page |

Three more that did not need an ADR but drove the shape of the work:

- **`bge` fails at startup, never at request time.** A fallback to `stub` would publish hash vectors as semantic embeddings, silently. This is where [ADR-009](../context/architecture.md#adr-009--a-stub-degrades-to-a-no-op-never-to-a-wrong-signal) is enforced in code rather than described.
- **Conversation history is text; only the final turn carries documents.** Replaying earlier `document` blocks would shift `document_index` and break every citation span, and would re-present content authorized under a stale ACL — the materialized authorization state [ADR-008](../context/architecture.md#adr-008--no-materialized-authorization-state) forbids.
- **R-059 was fixed by supplying the dependency, not by loosening the test.** The feedback test failed because `integration-db` had no inference service; the job now starts one. Weakening the assertion would have hidden the gap.

### Deviations from the task file

No task file — this was QA remediation, tracked by finding ID rather than by task.

Scope was also *not* expanded where it was tempting: `0001_initial` still uses `Base.metadata.create_all()`, so released migration history is still re-derived from current model metadata. `IF NOT EXISTS` in `0002` and `0003` contains the symptom; rewriting `0001` as explicit DDL is the real fix and is deliberately not in this round.

### Verification

[E-008](./test_evidence.md). Everything is local — no CI run on this tree. Notably absent: any live Anthropic call, so all answer-quality figures remain unmeasured, and any eval-harness run, so the E-007 retrieval numbers are superseded rather than carried forward — the embedder changed underneath them.

### Follow-ups

- **R-070 stays partial.** There is still no test driving `/chat/completions` with inference unreachable and asserting `503 retrieval-unavailable`; `test_chat.py` tolerates 503 in a status set rather than requiring it.
- **R-059 / R-061 are `resolved (local)`** until GitHub Actions is green on this commit.
- **R-030** (no `as_of` filter) and **R-031** (eval harness not in CI) remain open and pre-existing.
- Retrieval quality against real BGE-M3 is unmeasured — an eval run on a `--load-corpus` rebuild is the next measurement worth taking.

---

## 2026-07-26 — QA review of Milestone A, and remediation

**Status:** partial
**PR:** —
**Branch:** `main` (uncommitted working tree on `104facc`)

### What changed

A full QA pass over Milestone A — static review of all 9,071 LOC plus live black-box testing against a running stack — raised 37 findings (IS-01 … IS-37), of which 30 were remediated and verified over five rounds. The two headline defects were an SSE stream that died silently when inference was unavailable, and a groundedness verdict that in the shipped no-key configuration was decided by punctuation. Document versioning, ACL filtering on collections, the eval corpus loader, readiness probing, the RFC 7807 envelope, security headers and rate-limit headers were all closed. The frontend still has no authentication and the abstention rule now costs three answerable golden questions.

### Files touched

- `apps/api/src/api/routers/chat.py` — retrieval resolved before the stream opens; `GET /queries/{id}` audit read; rate-limit headers copied onto the `StreamingResponse`
- `apps/api/src/api/services/chat.py` — degraded-mode verdict, source selection and PT/EN degraded messages
- `apps/api/src/api/routers/documents.py` — version supersession, `POST`/`GET /documents/{id}/versions`, content dedup, multipart validation, 405 through the canonical problem path
- `apps/api/src/api/routers/collections.py` — ACL filtering on list and detail
- `apps/api/src/api/routers/admin.py` — `GET /admin/erasures`
- `apps/api/src/api/{main,problem}.py` — security-header middleware, `StarletteHTTPException` handler, `extra` on `problem_response`
- `apps/api/src/api/deps/limits.py` — `RateLimit-*` and `Retry-After`
- `apps/api/src/api/routers/health.py`, `apps/inference/src/inference/main.py`, `infra/compose/docker-compose.yml` — inference readiness and healthcheck wiring
- `packages/retrieval/src/retrieval/{lexical,pipeline}.py` — content-lexeme extraction, matched-term evidence, `lexical_evidence_hits` split from `hits`
- `packages/llm/src/llm/client.py` — `extractive_fallback` emits sources, not sentence-bound citations
- `packages/domain/src/domain/text.py` — HTML and binary signature rejection
- `evals/harness/corpus.py`, `packages/db/src/db/models.py` — bulk chunk delete, `passive_deletes`
- `apps/web/` — CSP and security headers, citation numbering, skip link, `aria-pressed`, status region, `NEXT_PUBLIC_DEV_AUTH` default

### Decisions

Degraded-mode evidence must be lexical or absent — recorded as [ADR-012](../context/architecture.md#adr-012--degraded-mode-evidence-is-lexical-or-it-does-not-exist). Three earlier gates were tried and each was inert; the measured spread of each gate's input is in [E-007](./test_evidence.md), which is now the standard this repo holds a threshold to.

The CSP uses `'unsafe-inline'` for Next's inline RSC payloads. A nonce-based policy is stronger and needs request middleware with nonce propagation; shipping a policy that leaves every control on the page inert was the worse option.

Buffer-then-verify streaming was kept deliberately: forwarding unverified tokens and retracting them would defeat the abstention gate. The product's time-to-first-token targets are unreachable under it and need rewording rather than the code changing.

### Deviations from the task file

No task file — this was a review pass, not a planned task.

### Verification

[E-006](./test_evidence.md) (review + remediation) and [E-007](./test_evidence.md) (the degraded-mode evidence rule). Local gate green: mypy 62 files, 54 passed / 1 skipped, ruff, format, import-linter, biome, tsc, `next build`, `git diff --check`.

### Follow-ups

R-059, R-061, R-070, R-071, R-072 open. Cross-lingual degraded answers blocked on T-105 (real BGE-M3 weights). CI is still red on R-059 and none of this round's acceptance checks run in CI.

---

## 2026-07-25 — Security & correctness pass — R-032 → R-057

**Status:** done
**PR:** —
**Branch:** main (commit `080a6bd`)

### What changed

A three-pass review (architecture, backend, frontend, then a security-only sweep) found 26 further issues. Six were verified by executing them against a live stack rather than by reading, and those six share one shape: **a control that was written down, scored, or filtered for, but never actually enforced.**

The most serious was silent. `confidence_floor = 0.05` was compared against raw retrieval scores, but under the default `hybrid_rrf` strategy an RRF score is bounded by `2/(k+1)` ≈ 0.033 — below the floor for every possible input. The abstention gate, the product's headline differentiator, returned `unsupported` for **100% of queries under the default configuration**, and nothing caught it: the eval harness stops at retrieval, and the chat tests assert only that the verdict is one of three legal strings. Same question, same corpus: `dense_only` → `grounded`, `hybrid_rrf` → `unsupported`, at identical citation coverage.

The same pattern, three more times. `injection_risk` had been scored on every chunk since Phase 1 and read by nothing, so architecture § 9's layered defense was one system-prompt sentence. `erased_at` was filtered in both retrieval arms while the endpoint that would set it did not exist — the 405 handler pointed callers at a 404. Every citation claimed `"staleness": "fresh"` as a hardcoded literal.

Two failure paths were broken in ways that hid their own failures: the worker wrote its failure bookkeeping inside a transaction that rolls back on exception (so failed jobs stayed `pending` forever with `attempts` permanently 0), and `upload_document`'s error handler died inside RLS because a mid-request commit had cleared the transaction-local tenant GUC.

On the security side: `archive` needed only read permission to remove a document from everyone's retrieval; feedback could be cast on other users' queries without limit; the upload allowlist trusted the client's `Content-Type`, and a NUL byte behind it wedged ingest with a 500; there was no rate limiting or budget enforcement at all; and every Compose port bound `0.0.0.0` while the stack ran `DEV_AUTH_BYPASS=true` with default credentials and an unauthenticated Celery broker.

### Files touched

- `packages/llm/` — `normalize_scores`, offset-based citation indices, `JudgeResult`, index-matched entailment parsing
- `packages/retrieval/` — injection filtering in both arms, `injection_risk` propagation, atomic ACL version bump
- `packages/domain/` — new `text.py` (NUL sanitation, content sniffing), injection thresholds
- `packages/db/` — tenant context re-applied on `after_begin`; migration `0002_security_fixes`
- `apps/api/` — `deps/limits.py`, `routers/admin.py`, real `/ready`, WRITE checks on archive, feedback ownership + dedup, content-based upload validation, staleness computation, judge cost ledger
- `apps/worker/` — three-transaction ingest, NUL-safe parsing
- `apps/web/` — `lib/api.ts`, `lib/sse.ts`, span-linked citations, dark mode, labels and live regions, abort support, ingest polling
- `infra/`, `.github/` — loopback binding, multi-stage web image with build args, `next build` and Redis in CI

### Decisions

Two new ADRs, both generalising a specific failure into a rule:

| ADR | Rule |
| --- | --- |
| [ADR-010](../context/architecture.md#adr-010--thresholds-compare-normalized-values-never-raw-scores) | Thresholds compare normalized values, never raw scores. Raw scores from different strategies are not comparable to a shared constant. |
| [ADR-011](../context/architecture.md#adr-011--a-signal-that-nothing-reads-is-not-a-control) | A signal that nothing reads is not a control. Ship the code that acts on a signal in the same change that computes it. |

Rate limiting fails **open** on a Redis outage (a cache failure should not be a full outage) while the budget guard reads Postgres and does not, so cost protection survives what request-rate protection does not. That asymmetry is deliberate.

### Deviations from the task file

No task file — this was review remediation, tracked in [review_notes.md](./review_notes.md) as R-032 → R-057.

One self-inflicted regression is recorded as R-057: caching the SQLAlchemy engine on the worker module to avoid rebuilding it per job broke the Celery path, because the entrypoint calls `asyncio.run` per task and a cached engine holds connections bound to a closed event loop. It surfaced only when the integration tests ran in sequence, and was reverted. Worth remembering that the "obvious" pooling optimisation is wrong wherever the event loop is per-invocation.

### Verification

**59 passed** with the full environment loaded (was 40 before this pass); **45 passed, 1 skipped** in the unit-only configuration CI runs. `ruff`, `ruff format`, `mypy --strict`, `lint-imports` (5/5 contracts), `biome`, `tsc --noEmit`, and `next build` all clean. Migration `0002` round-trips up → down → up.

Six fixes were verified by executing the original defect against a live stack and confirming the behaviour changed — see [test_evidence.md](./test_evidence.md) E-004.

### Follow-ups

- **R-030** (no `as_of` filter) and **R-031** (evals not in CI) remain open and unscheduled.
- **R-046**: the 20 duplicate documents that earlier test runs left in the local `acme` tenant are still there. Clear them before quoting eval numbers, since `recall@10 = 0.909` was measured against a corpus containing them.
- The dev-user impersonation dropdown is now gated behind `NEXT_PUBLIC_DEV_AUTH`, but the frontend still has **no real authentication path** — no OIDC flow, no token handling. It functions only against an API running `DEV_AUTH_BYPASS=true`.
- No frontend test framework was introduced; `lib/sse.ts` is the natural first candidate.

---

## 2026-07-25 — Milestone A review remediation — R-009 → R-029

**Status:** done
**PR:** —
**Branch:** chore/T-001-monorepo-scaffold

### What changed

Implementation review of the Milestone A MVP found 23 issues, 21 fixed here. The headline is that **role-based access control existed but was never attached to a route**: `require_role` had no call site, so any authenticated user — including `viewer` — could create ACL entries granting themselves read on the whole tenant. Alongside it, three placeholders were fabricating signal rather than degrading to no-ops (zero-vector embeddings producing NaN cosine distances, a rerank stub sorting by document length as the default strategy's final stage, and an eval harness scoring the gold set against itself), and the groundedness gate was emitting its abstention message *after* streaming the ungrounded answer it was meant to suppress.

The eval harness was rebuilt rather than patched: it now ingests a fixture corpus through the real worker pipeline and calls `retrieve()` per item, producing the first genuine retrieval numbers for this system.

### Files touched

- `apps/api/src/api/deps/auth.py` — `CuratorUser` / `AclAdminUser` aliases; OIDC path now reads roles from the database, not token claims
- `apps/api/src/api/routers/{acl,collections,documents}.py` — role gates attached; ACL predicate applied to document metadata reads; upload gained an ACL `write` check, a streaming size cap (413), and a MIME allowlist (415)
- `apps/api/src/api/services/{chat,ingest}.py` — answer withheld until the groundedness verdict exists; blocking calls moved off the event loop
- `apps/inference/src/inference/deps.py` *(new)* — service-token enforcement
- `apps/inference/src/inference/routers/{embed,rerank}.py` — hashed unit vectors; identity rerank
- `packages/retrieval/src/retrieval/acl.py` — all roles load, not one arbitrary row
- `packages/llm/src/llm/client.py` — `max_tokens` headroom for thinking; retries scoped to transient errors
- `apps/worker/src/worker/pipeline/index.py` — batched FTS updates
- `evals/corpus.json`, `evals/harness/corpus.py` *(new)*, `evals/harness/run.py` — live retrieval scoring
- `evals/fixtures/{onboarding_guide_en,ma_deal_legal,hr_remote_work_v1,hr_remote_work_v2}.md` *(new)* — corpus backing the previously unbacked gold labels
- `infra/compose/docker-compose.yml`, `.env.example` — auth-bypass default flipped to `false`; missing `DATABASE_URL_MIGRATE` override added
- `apps/{api,inference}/tests/` — negative-path tests for every control added

### Decisions

- **Default strategy moved from `hybrid_rerank` to `hybrid_rrf`.** A stub cannot satisfy the Phase 2 exit criterion that reranking beat RRF, and the length-sorting stub was actively degrading fused order. Reverts when real weights land (T-206).
- **Inference service token is enforced when set, open when unset.** Not fail-closed: an unreachable embedder breaks ingest rather than leaking, and the service holds no tenant data. Recorded in [architecture § 3.2](../context/architecture.md#32-inference-service-contract).
- **Roles read from Postgres even on the OIDC path.** `require_role` and `resolve_acl` must agree about a caller; only one of the two can read a JWT.
- **Buffering the model stream was accepted over live typing.** An abstention that arrives after the text it suppresses is not an abstention. Reinstating live streaming needs a client-honoured `retract` event, not a reordering.
- Recorded as [ADR-009 — a stub degrades to a no-op, never to a wrong signal](../context/architecture.md#adr-009--a-stub-degrades-to-a-no-op-never-to-a-wrong-signal).

### Deviations from the task file

No task file — this was review remediation, not a planned task. Two findings were left open deliberately: R-030 (retrieval has no `as_of` filter, so the `versioned` slice scores 0.50) and R-031 (evals not in CI, which needs an inference service in the workflow). Both are real gaps now visible in the numbers rather than hidden behind a synthetic 1.0.

### Verification

`ruff` + `ruff format` + `mypy` (59 files) + `import-linter` (5/5 contracts) clean. **39 passed, 0 skipped** with the environment loaded — the RLS isolation and ingest/search integration tests actually ran, which was not previously true. First real eval numbers: overall `recall@10 = 0.909`, `nDCG@10 = 0.627`. ACL isolation verified end-to-end through the `permission` slice: `acme-viewer` retrieves only the restricted legal document, `acme-member` retrieves everything except it. See [test_evidence.md](./test_evidence.md) E-003.

### Follow-ups

R-030 (`as_of` point-in-time retrieval) and R-031 (evals in CI) are open in [review_notes.md](./review_notes.md). Neither is scheduled.

---

## 2026-07-25 — Milestone A MVP — Foundation through chat UI

**Status:** done
**PR:** —
**Branch:** chore/T-001-monorepo-scaffold

### What changed
Shipped Milestone A vertical slice: monorepo + Compose + RLS tenancy + OIDC/dev auth + document ingest (PDF/MD/TXT) + ACL-aware hybrid retrieval + SSE chat with groundedness/abstention + eval datasets/harness + Next.js chat/admin UI. Inference and generation degrade to stubs/extractive when models/API keys are absent.

### Files touched
- `apps/{api,worker,inference,web}` — services and UI
- `packages/{domain,db,retrieval,llm,observability}` — shared libraries
- `infra/compose/` — Postgres/Redis/MinIO/Keycloak stack
- `evals/` — eight-slice golden set + metrics harness
- `.github/workflows/ci.yml` — lint/typecheck/unit/integration-db

### Decisions
- `DEV_AUTH_BYPASS` + `X-Dev-User` for local demos without Keycloak.
- `INGEST_SYNC=true` runs the ingest pipeline inline so demos need no Celery worker.
- Real BGE weights deferred; HTTP contract preserved.
- Live Anthropic optional; extractive fallback + abstention when unsupported.

### Deviations from the task file
Phases 0–6a landed on one long-lived branch for portfolio velocity; split into per-task PRs if review prefers.

### Verification
See test_evidence.md E-002.

### Follow-ups
Real BGE models; live citation eval gates; Milestone B.

---

## 2026-07-25 — T-001 — Monorepo scaffold

**Status:** done
**PR:** —
**Branch:** chore/T-001-monorepo-scaffold

### What changed
Monorepo layout, uv workspace, lint/type tooling, and stub api/worker/inference/web services are in place so Phase 0 can build on a real skeleton.

### Files touched
- `apps/*`, `packages/*` — service and package skeletons
- `pyproject.toml`, `Makefile`, `.importlinter`, `.env.example` — toolchain
- `apps/web` — Next.js App Router + Biome

### Decisions
Inference stubs return fixed 1024-dim zeros rather than loading BGE weights (T-105). Inference does not import `domain` to satisfy import-linter.

### Deviations from the task file
None.

### Verification
See test_evidence.md E-001.

### Follow-ups
T-002 Compose stack.

---

## 2026-07-25 — Review remediation — Eight findings + milestone split

**Status:** done
**PR:** —
**Branch:** —

### What changed

An architecture review of the planning documentation returned eight findings (1 critical, 3 high, 4 medium) plus a high-delivery-risk verdict. All eight are resolved and registered as `R-001`–`R-008` in [review_notes.md](./review_notes.md). The v1 boundary is now split into two milestones.

### Decisions

**Three findings were factual errors, not disagreements** — the docs stated things that were untrue:

- `DELETE /documents/{id}` cascading to all versions cannot coexist with resolvable historical citations. Replaced by archival plus a privileged erasure path that keeps tombstones and nulled citations, so a historical answer degrades to "source erased" rather than dangling.
- Presigned S3 URLs were described as "scoped to the requesting user." They are bearer credentials. Proxied download is now the default; presigning is opt-in with its revocation window documented.
- The prompt-injection suite was a per-commit merge gate on a probabilistic signal. Split into deterministic contract tests (per-commit) and a live adversarial tier (nightly, blocks release not merge).

**Two were premature security infrastructure I introduced** — an overprivileged Celery role and a materialized `user_visible_documents` table. Both removed; the latter is now [ADR-008](../context/architecture.md#adr-008--no-materialized-authorization-state), which reverses a documented design element and says why.

**Milestone split, with two amendments to the reviewer's cut.** Milestone A is a deployable portfolio release carrying **all six differentiators**; Milestone B adds breadth (DOCX/HTML/EML, OCR, budgets, full admin, Terraform). Against the reviewer's proposal, document-level deny overrides and the `cost_ledger` table stay in A: `acl_entries` is already polymorphic so deny-precedence is cheap now and is exactly where an access-control bug would live, and "no un-ledgered LLM call" is a stated design principle that costs one table to honor.

**Two benchmark profiles** — `dev-cpu` and `cloud-gpu` — now sit behind every SLO. The original targets were not reachable on CPU, where the reranker alone consumes the whole retrieval budget; publishing them as universal would have meant every local measurement failing an SLO the environment could never meet.

### Files touched

`architecture.md` (§ 4.2 roles, § 5.3 predicate + revocation, § 6.4 removal, § 14 data model → 21 tables, ADR-008) · `api_rules.md` (archive/erase endpoints, § 13.1 presigned URLs) · `testing.md` (tier split, § 6.3 contract tests, § 7.5 adversarial, § 9 profiles) · `roadmap.md` (two milestones, per-phase tagging, coverage matrix) · `product.md` (§ 5 scope tagging, § 7.4 profiles) · all four `execution/` files.

### Deviations from the plan

None. Two amendments to finding 4 were raised before starting and confirmed.

### Verification

Twelve consistency checks — see [test_evidence.md](./test_evidence.md) entry `E-001`.

### Follow-ups

None open. Two recurring themes recorded in [review_notes.md](./review_notes.md) as standing checklist items.

---

## 2026-07-25 — Planning — Project documentation

**Status:** done
**PR:** —
**Branch:** —

### What changed

Populated the `docs/` scaffold with the full project plan for the Enterprise RAG Document Intelligence System. The repository now has a complete design, standards set, and phased roadmap. No code was written — this was explicitly a documentation-only phase.

### Files touched

- `docs/context/product.md` — problem, personas, scope, differentiators, success metrics, user stories, open questions
- `docs/context/architecture.md` — component topology, tenancy model, ACL model, versioning, retrieval pipeline, generation and citations, injection defense, groundedness, evaluation, cost and observability, resilience, data model, seven ADRs, repo layout, deployment
- `docs/context/roadmap.md` — eight dependency-ordered phases with exit criteria, plus a deferred list and a requirement-coverage matrix
- `docs/standards/conventions.md` — toolchain, module boundaries, Python and TS style, database and migration rules, config, logging, git, definition of done
- `docs/standards/api_rules.md` — versioning, auth, resource conventions, RFC 7807 errors, streaming, rate limits, full v1 endpoint inventory
- `docs/standards/testing.md` — seven test tiers, coverage targets, the security suite, eval gates, determinism policy, CI pipeline
- `docs/standards/ai_agent_rules.md` — repo working rules plus the LLM-integration constraints that produce 400s or silent breakage if violated
- `docs/tasks/README.md`, `docs/tasks/TEMPLATE.md` — task numbering, lifecycle, and spec template
- `docs/execution/*.md` — current task pointer, this log, review register, evidence log
- `README.md` — project overview and docs index

### Decisions

Seven decisions were locked during planning and recorded as ADRs in [architecture.md § 15](../context/architecture.md#15-architecture-decision-records):

| Decision | Rationale in short |
| --- | --- |
| Thin custom LLM layer, no LangChain/LlamaIndex | The load-bearing parts (ACL-aware retrieval, native citations, injection defense, cost ledger) are exactly what a framework abstracts away or does not model |
| Postgres-only search (pgvector + FTS), no vector DB | ACL pre-filtering is a `WHERE` clause in one store and a consistency problem across two |
| Postgres FTS over OpenSearch in v1 | Same-store fusion, same ACL predicate, no second cluster; `KeywordSearch` interface leaves the door open |
| Self-hosted BGE-M3 embeddings | Anthropic ships no embeddings endpoint; BGE-M3 is strong on PT+EN, costs nothing per token, and keeps content in-house |
| Self-hosted BGE-reranker-v2-m3 | Pairs with BGE-M3, multilingual, no extra vendor on the critical path |
| Native Anthropic citations over prompt-numbered markers | Spans come from the API, so a fabricated citation is structurally impossible |
| Chunks belong to document *versions*, not documents | Makes supersession a metadata update and keeps old citations permanently resolvable |

Supporting assumptions, stated rather than deferred: AWS ECS Fargate as the cloud target (with GCP Cloud Run documented as the alternative), Celery + Redis for async jobs, OIDC/JWT with Keycloak locally.

### Deviations from the task file

No task file — this predates task tracking. `T-001` is the first tracked task.

### Verification

Documentation review only; no tests exist yet. See [test_evidence.md](./test_evidence.md) for the review checklist that was applied.

### Follow-ups

Four open questions are recorded in [product.md § 10](../context/product.md#10-open-questions) and scheduled for resolution: Q-1 and Q-2 by experiment in Phase 4, Q-3 and Q-4 as product decisions in Phases 3 and 6.

## 2026-09-06 — R-070 local implementation

Reconciled stale handoff against committed July 31 QA remediation. Added strict
JSON/SSE chat transport-outage tests; negative stream-order mutation detected.
Ruff, formatting, mypy, and unit suite pass (83 passed, 1 skipped, 15 deselected).
No release completion or CI claim; full scope and US$25 ceiling remain unchanged.

## 2026-09-06 — R-030 local implementation

Added shared UTC parsing and half-open version filtering through search, chat,
retrieval arms and evaluation dates. Exact historical citations and current
security controls verified on disposable Postgres under all four strategies.
Regenerated contracts/types. Full Phase 4, R-031, experiments and release
evaluation are still unimplemented; Milestone A is not complete.

## 2026-09-07 — T-401 local implementation

Added a reproducible synthetic source catalog and renderer: 40 bilingual operational
scenarios, dated policy revisions, routing and restricted records, eight balanced
attack families, and 40 conflicting Globex counterparts. Added strict manifest
validation for hashes, safe paths, intervals, tenant groups, labels, and privacy.
Renderer, parser/chunker, manifest tests, Ruff, and mypy pass. Full suite: 122
passed, 1 existing dependency skip, 19 integration deselections. No paid calls or
CI evidence; database load remains for the evaluation foundation tasks.

## 2026-09-07 — T-402 local implementation

Generated the eight immutable golden JSONL slices from the T-401 catalog, exactly
40 cases each. Added explicit labels, expected facts, PT/EN direction checks,
version boundary/current/absent cases, acting users, prohibited sources, and
abstention expectations. Dataset validation and reproducibility checks pass; no
model calls, CI result, or quality score was produced.

## 2026-09-07 — T-403 local implementation

Completed retrieval metrics with precision@10, explicit empty-gold behavior,
duplicate-version collapse, and per-slice/language aggregation. The production
harness validates the dataset before retrieval and deduplicates mapped version
labels before scoring. Focused tests, Ruff, and mypy pass; no quality baseline or
real-model result was changed.

## 2026-09-07 — T-404 local implementation

Moved entailment judging to the versioned `entailment_v1` rubric under
`evals/harness/judges`, recorded its SHA-256 and Haiku model identity, and added
strict parsing. Missing, duplicate, malformed, or out-of-range labels now produce
an explicit incomplete result and cannot upgrade groundedness. Focused judge tests,
Ruff, and mypy pass; no live judge call or paid spend occurred.
