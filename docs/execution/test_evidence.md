# Test Evidence

> Record of what was actually run and what it showed. Not a plan — a record.
> **Related:** [../standards/testing.md](../standards/testing.md) · [work_log.md](./work_log.md) · [review_notes.md](./review_notes.md)

Claiming a task is done requires an entry here. "Tests pass" without a command and an output is not evidence.

---

## Entry format

```markdown
### E-NNN — YYYY-MM-DD — T-XXX

**Environment:** local | ci | staging
**Commit:** <short sha>

| Command | Result |
| --- | --- |
| `<exact command>` | <pass/fail + the number that matters> |

**Acceptance criteria verified:**
- [x] <criterion> — how it was checked

**Notes:** <anything surprising; skipped checks and why>
```

---

### E-009 — 2026-07-29 — QA review and five remediation rounds (R-078 → R-098)

**Environment:** local, **no services running**. Postgres, Redis, MinIO, Keycloak, inference and the API were all down for the whole exercise — the review was commissioned as static-evidence-only, and every number below was produced without them. Integration tests are therefore deselected throughout, and no row here says anything about live retrieval quality.
**Commit:** working tree on `5b26159`
**Report:** [qa_report_2026-07-29.md](./qa_report_2026-07-29.md) — findings in §1–§8, per-round verification in §9–§13.

**What "no services" costs, stated plainly:** ten of the twenty findings were proven by executed evidence — pure functions probed directly, SQL compiled against the Postgres dialect, git plumbing, and the offline test tiers. The other ten are marked *Potential Concern* in the report and rest on source that admits one reading. Nothing here verifies end-to-end behaviour against a running stack.

**Final gate** (after round 5; the intermediate rounds are in the report):

| Command | Result |
| --- | --- |
| `uv run ruff check .` | pass |
| `uv run lint-imports` | pass — **5 contracts kept, 0 broken** (`domain.embeddings` respects the layering) |
| `uv run pytest -q` | **80 passed, 1 skipped, 14 deselected** (from 74 at E-008) |
| `make openapi-check` | in sync — the three new `ErasureLog` fields reached both schema and generated client |
| `cd apps/web && npx biome check .` | pass — **25 files** |
| `cd apps/web && npx tsc --noEmit` | pass |
| `cd apps/web && npx vitest run` | **11 passed** across 6 files (from 9 across 5) |

**Behavioural probes** — the checks that actually decided findings, as opposed to the gate above, which passed at `5b26159` too and saw none of them:

| Check | Method | Result |
| --- | --- | --- |
| R-080 — policy prose blocked | `score_injection_risk()` over 8 realistic policy sentences | 5 at ≥ 0.8 before; all < `BLOCK` after |
| R-080 — bypass after fix attempt 1 | 5 override-only attacks avoiding the exemption's vocabulary | **all 0.00** — fix rejected |
| R-080 — both directions after attempt 2 | 6 attacks + 8 benign + 2 realistic 512-token chunks | 6 bypasses at 0.00 **and** 3 false positives at 0.90; policy chunk 0.90 blocked, attack chunk 0.00 — fix rejected |
| R-080 — after attempt 3 (band split) | same probe sets, plus 4 structural markers | policy chunk 0.75 retrieved, attacks 0.75 labelled, structural 0.95 blocked |
| R-080 — `[UNTRUSTED]` reaches the model | `is_suspect` → `_document_blocks()` title | `Security Policy [UNTRUSTED: contains instruction-like text]` |
| R-081 — dead verdict input | `groundedness_verdict()` across 4 label sets | all-`unrelated` → `grounded` before, `unsupported` after |
| R-082 — array predicate is real SQL | compile under the PostgreSQL dialect | `retrieved_chunk_ids && %(param)s::UUID[]` — not a Python-side filter |
| R-082 — ordering constraint holds | **mutation test**: hoist `delete(Chunk)` above the redaction, re-run | **test failed** under the mutation, passed after byte-identical restore |
| R-085 — detectors disagree | both detectors over 4 bilingual queries | `pt`/`en` split before; agree after |
| R-086 — version derivation | `embedding_model_meta()` over the 6-row env matrix | all six correct, incl. stale `stub-v0` ignored under `bge` |
| R-090 — splitters stay identical | Python vs JS over 10 cases incl. `Sec.`, `Dr.`, `Inc. Ltd.`, no-terminator | **0 mismatches**, before and after the Biome refactor |
| R-078 / R-083 — clean-clone reality | `git check-ignore -v`, `git ls-files` | template untracked (fixed); `docs/` 0 files tracked (`wont-fix`) |
| R-079 — Compose without `.env` | `docker compose config` with the file absent | exit 1 after fix attempt 1; **exit 0** after round 2 |

**Notes:**

- **The gate does not see behaviour.** Every command in the first table passed at `5b26159`, with all twenty findings present. The second table is where the findings came from. Recorded because E-008's table looks identical and carries the same limitation.
- **Two fixes were rejected on evidence before the third was accepted** (R-080). Both rejected attempts passed the full suite, because their tests were the strings the reviewer had published rather than the class those strings illustrated. The accepted fix is asserted against named thresholds (`INJECTION_RISK_FLAG <= score < INJECTION_RISK_BLOCK`), which is what lets the suite see a banding regression rather than a wording one.
- **One finding was verified by breaking the code on purpose.** R-082's ordering pin was only accepted after `delete(Chunk)` was hoisted above the redaction and the test was observed to fail. An ordering assertion that has never been seen to fail is not evidence that the ordering is enforced.
- **Still unmeasured, and not measurable this way:** answer quality, latency, and cost against the live Anthropic API; retrieval metrics against a real corpus; anything requiring a browser. Unchanged from E-008 and from the report's §1.

---

### E-008 — 2026-07-27 — Milestone A closing round (R-059, R-061, R-070 → R-077)

**Environment:** local. Compose Postgres :15432, Redis :16379, MinIO :19000, Keycloak :8080, API :8000, web :3000. Inference **real BGE-M3 / BGE-reranker-v2-m3 on CPU** unless a row says otherwise. **No `ANTHROPIC_API_KEY`** — every answer-quality column below is therefore still unmeasured.
**Commit:** working tree on `104facc`

| Command | Result |
| --- | --- |
| `uv run ruff check .` · `ruff format --check .` | pass · **106 files** formatted |
| `uv run mypy` | pass — no issues in **64 source files** |
| `uv run lint-imports` | pass — **5 contracts kept, 0 broken** |
| `uv run pytest -q -m 'not integration'` | **74 passed, 1 skipped, 14 deselected** |
| `make test-integration` | **11 passed, 3 skipped** — disposable database created, migrated, seeded, dropped |
| `cd apps/web && npx biome check .` | pass — **23 files** |
| `cd apps/web && npx tsc --noEmit` | pass |
| `cd apps/web && npm run test:coverage` | **9 passed**; 72.31% stmts / 58.58% branch / 78.26% funcs / 74.14% lines |
| `cd apps/web && npx next build` | pass — Next.js 16.2.12 production build |
| `make openapi-check` | `>> openapi.json is in sync with the code` |
| `npm run generate:api-types` + `git diff --exit-code` | clean — generator output is deterministic |
| `docker compose … config -q` | pass |
| `git diff --check` | pass |
| `cd apps/web && npm audit --omit=dev` | **0 vulnerabilities** |

**Acceptance criteria verified:**

- [x] **OIDC end to end (R-072)** — sign-in through Keycloak with Authorization Code + PKCE, `GET /api/v1/me` returning 200 through the proxy, refresh rotation returning 200, logout clearing the session. Tokens confirmed absent from the page: only `HttpOnly` cookies.
- [x] **Real embeddings (T-105 / IS-07)** — live CPU call returned **1024-dimensional L2-normalized** vectors, and the reranker scored the relevant passage **≈7000× above** an unrelated one. This is the first retrieval measurement in this log taken against real weights.
- [x] **Backend selection fails closed (R-075)** — an unknown `INFERENCE_BACKEND` value raises at startup; `bge` without the `models` extra raises rather than falling back to `stub`.
- [x] **Disposable test database (R-071)** — the run created, migrated, seeded, used and dropped its own database; the development database was untouched. A URL naming a non-`_test` database is refused before any connection.
- [x] **Migrations from empty** — `upgrade head → downgrade -1 → upgrade head → seed` through `0003`, from an empty database, then dropped.
- [x] **Keyset pagination (R-076)** — cursors round-trip microsecond precision and UUID bytes; malformed cursors raise `ValidationError`; `next_cursor` is emitted only when a further row exists.
- [x] **Multi-turn bounds (R-077)** — the legacy `question` contract still works; a `messages` conversation uses the latest user turn with bounded history; invalid conversations are rejected.

**What did not run, and what that means:**

- **No CI run on this tree.** Every number above is local. R-059 and R-061 were failures observed *only* in GitHub Actions, so they are recorded as `resolved (local)` and are not closed until Actions is green on this commit. Reporting a local pass as a CI fix is exactly the overstatement this log exists to prevent.
- **No live Anthropic call.** Faithfulness, citation precision, answer relevance, end-to-end latency, cost per query and injection success rate remain `n/m`. The system ran in the degraded no-key path throughout, so no verdict here is evidence about generation.
- **No eval-harness run in this round.** The retrieval figures in E-007 were measured under stub embeddings and do **not** carry over — the embedder changed. Retrieval quality against real BGE-M3 is unmeasured, and the last recorded numbers should be read as superseded, not as a baseline.
- **3 integration tests skipped**, consistent with earlier rounds.
- **Frontend coverage is reported, not gated**, and the admin page is the largest uncovered area.

**Notes:** the full `npm audit` (including dev) reports four high-severity advisories, all reachable only through the `openapi-typescript` generation chain. The gate is `--omit=dev`, which is clean. Forcing overrides breaks the generator; the advisories are recorded rather than force-resolved, and the dev-only claim was checked against the dependency path rather than assumed from where the packages sit in `package.json`.

---

### E-007 — 2026-07-26 — Degraded-mode evidence rule (R-062, R-067)

**Environment:** local (Compose Postgres :15432, Redis :16379, MinIO :19000, inference stub :8001, API :8000, `DEV_AUTH_BYPASS=true`, **no `ANTHROPIC_API_KEY`**, stub embeddings)
**Commit:** working tree on `104facc`

| Command | Result |
| --- | --- |
| `uv run mypy` | pass — no issues in 62 source files |
| `uv run pytest -q -m 'not integration'` | **54 passed, 1 skipped, 13 deselected** |
| `uv run ruff check .` · `ruff format --check .` | pass · 96 files formatted |
| `uv run lint-imports` | pass — 5 contracts kept |
| `cd apps/web && npx biome check . && npx tsc --noEmit && npx next build` | pass |
| `git diff --check` | clean |

**Golden-set abstention sweep** — all 14 items in `evals/datasets/*.jsonl`, each sent to `POST /api/v1/chat/completions` as its own `acting_user`, 6 s apart to stay under the 10/min chat cap:

| Metric | Before ADR-012 | After |
| --- | --- | --- |
| Missed abstentions (`should_abstain=true` answered) | 2 | **0** |
| False abstentions (`should_abstain=false` abstained) | 0 | 3 |
| Stop-word probes returning sources | 3 of 4 | **0 of 4** |

Probes, all → `unsupported`, 0 sources: `"Is the of a and for to?"`, `"Is the what of the next for is?"`, `"What is the thing for the next one?"`, `"zzzqqq xyzzy plugh"`.

**The three false abstentions are one cause** — the question shares no stem with its source, so lexical evidence cannot exist and the semantic arm is a SHA-256 hash:

- `perm-001` — question lexemes `{deal, m, valuat}`; the document says *"valued at USD 240 million"* (`valu`, not `valuat`) and never says "deal". Matched terms: 1.
- `xl-001` — Portuguese question, English source. Primary-config lexemes `{é, períod, rotaçã, senh}` match **0** English chunks. No FTS rule bridges this.
- `inj-001` — the only chunk matching `'summar'|'onboard'|'guid'` carries `injection_risk = 0.85` against `INJECTION_RISK_BLOCK = 0.8` and is filtered from both arms. No retrievable evidence exists; the fixture's `should_abstain: false` is questionable.

**Measured input spread for the rejected gates** (the number the new recurring theme asks for):

| Gate | Gibberish | Real question | Separates? |
| --- | --- | --- | --- |
| `retrieval_confidence` ≥ 0.15 | 0.3592 | 0.3592 | **no** |
| single shared lexeme, `ts_rank_cd` | 1.4 (`next`) | 0.8 (two terms) | **no — inverted** |
| distinct matched content lexemes ≥ 2 | 0–1 | 2+ | yes |

**Acceptance criteria verified:**
- [x] Degraded fallback cannot return `grounded` — forced `partial`, or `unsupported` with no sources
- [x] Fallback citations carry `answer_sentence_idx = -1` — observed `[-1, -1, -1]` on the SSE stream
- [x] A question with no content words abstains and attaches nothing
- [x] `citation_coverage` stays numeric (`0.0`), preserving the SSE and audit contract

**Acceptance criteria not verified:**
- [ ] `perm-002` measures the ACL gate — it currently passes for a lexical reason, and `acme-member` still holds a leftover test grant on `Acme Legal` (R-071)
- [ ] Any of this runs in CI. The sweep is a manual shell loop (R-070)
- [ ] Cross-lingual degraded answers — blocked on real BGE-M3 weights (T-105)

---

### E-006 — 2026-07-26 — QA review of Milestone A, and remediation

**Environment:** local, as E-007. Static review of all 9,071 LOC plus live black-box testing.
**Commit:** `104facc` (review) → working tree (remediation)

| Command | Result |
| --- | --- |
| `uv run pytest -q -m 'not integration'` (at review time) | 45 passed, 1 skipped, 13 deselected |
| `uv run python -m evals.harness.run` | overall `recall@10 = 0.364`; `crosslingual` **0.000**; `factual_en` 1.000 |
| `uv run python -m evals.harness.run --load-corpus` | **crashed** — `AssertionError: … blank-out primary key column 'chunk_embeddings.chunk_id'` (R-065); passes after the fix, twice consecutively |
| chat with inference stopped | before: `200` + one `status` event then silence, server log `RuntimeError: Caught handled exception, but response already started.`; after: **`503 retrieval-unavailable`** problem+json, zero occurrences in the log |
| `curl -I` on `/ready` with inference stopped | `503 {"status":"degraded","checks":{…,"inference":false}}` |
| 12 rapid `POST /chat/completions` | `200×10` then `429×2`, with `retry-after: 48` and the `RateLimit-*` triple |
| upload → `POST /documents/{id}/versions` → re-upload | `202` → `version_no 2` with `effective_to` set on v1 → `409` on identical bytes |
| upload of `.ico`, ZIP, HTML, pseudo-PNG | `415` on all four |
| `acme-viewer` `GET /collections` | `['Acme Legal']` only — was both collections |
| `GET /api/v1/queries/{id}` | owner 200 · other user 404 · admin 200 · cross-tenant 404 · malformed uuid **422** |
| `next start` + CSP inspection | 6 nonce-less inline `<script>` under `default-src 'self'` (R-066); after the fix `script-src 'self' 'unsafe-inline'` covers them and `connect-src` follows `NEXT_PUBLIC_API_BASE` |

**37 findings raised (IS-01 … IS-37).** Register entries: R-062 … R-072. Full report: [qa_report_2026-07-26.md](./qa_report_2026-07-26.md).

**Notes:** every number above was measured with stub embeddings, an identity reranker and no LLM. Answer quality, citation precision, injection-success rate, time-to-first-token and cost are therefore **unmeasured**, not passing. The dev corpus was polluted before the review began (45 documents, duplicate titles, test-created ACL rows) and the review added 12 more probe documents; retrieval numbers carry that caveat (R-046, R-071).

---

### E-005 — 2026-07-25 — GitHub Actions integration failure (R-059 → R-061)

**Environment:** GitHub Actions `integration-db` job (Postgres + Redis; no inference service)
**Commit:** `104facc`

| Command | Result |
| --- | --- |
| `uv run pytest -q -m integration` | **failed — 1 failed, 9 passed, 3 skipped, 46 deselected** |

**Failure:**

- `test_feedback_rejects_another_users_query` called `/chat/completions` to create a
  query fixture.
- Default `hybrid_rrf` retrieval attempted `POST /v1/embed`.
- No inference service was running, so `httpx.ConnectError` became
  `InferenceUnavailable`.
- The SSE response had already sent its HTTP status, so Starlette replaced the
  handled domain error with `RuntimeError: Caught handled exception, but response
  already started.`

**Secondary diagnostics:**

- The cached Redis client was reused from a different event loop, causing
  `Future attached to a different loop`; rate limiting then failed open as designed.
- Auth-engine teardown ran through another `asyncio.run()` loop and emitted
  `Event loop is closed` while closing pooled asyncpg connections.
- These event-loop errors are real findings, but they are not the cause of the
  initial inference connection failure.

**Unsafe remediation explicitly rejected:** returning `[0.0, 0.0, 0.0, 0.0]` from
`embed_query()` when `EMBEDDING_MODEL_VERSION=stub-v0`. The database column is
`vector(1024)`, zero-vector cosine distance is undefined, passage embeddings still
come from the inference service's SHA-256 unit-vector implementation, and
`stub-v0` is the normal development setting rather than a test-only switch.

**Acceptance criteria not verified:**

- [ ] Integration merge gate is green.
- [ ] Feedback ownership is tested without unrelated inference availability.
- [ ] An inference outage produces a defined pre-response error or terminal SSE event.
- [ ] Async Redis and identity-engine resources stay on the event loop that owns them.

See [R-059 through R-061](./review_notes.md) for the separated findings.

---

### E-002 — 2026-07-25 — Milestone A MVP

**Environment:** local (Compose Postgres on :15432, MinIO :19000, Redis :16379)
**Commit:** (uncommitted)

| Command | Result |
| --- | --- |
| `make lint` | pass (after final fixes) |
| `make typecheck` | pass (mypy + import-linter + tsc) |
| `make test` | ~~35 passed~~ — **see correction below** |
| `uv run python -m evals.harness.run` | ~~14 items, 8 slices, wiring metrics OK~~ — **see correction below** |
| `packages/db/tests/test_rls.py` | ~~2 passed (cross-tenant blocked)~~ — **see correction below** |

**Acceptance criteria verified:**
- [x] Two demo tenants seeded (acme, globex)
- [x] Cross-tenant isolation with RLS backstop
- [x] Document upload + sync ingest + search
- [x] Chat SSE with abstention / groundedness verdict
- [x] Eval dataset slices present; harness runs
- [x] Chat + admin UI pages exist

**Notes:** Embedding/reranker are stubs (dim 1024 / length scores). Generation uses extractive fallback without a real Anthropic key. Host ports remapped when 5432/6379/9000 busy.

> **Correction (2026-07-25, E-003).** Three figures in this entry did not mean what they
> said, and the pattern is recorded as a recurring theme in
> [review_notes.md](./review_notes.md#recurring-themes):
>
> - **"35 passed"** was 32 passed **+ 3 skipped**. Without `DATABASE_URL`, MinIO, and
>   inference reachable, the chat and both RLS tests skip silently *(R-028)*.
> - **"RLS isolation tests green"** described tests that had **not run** in that
>   environment — they were among the three skips.
> - **"wiring metrics OK"** came from a harness that scored `gold_chunk_ids` against
>   themselves and never called `retrieve()` *(R-018)*.
>
> This entry is left as written. The verified run is E-003.

---

### E-003 — 2026-07-25 — Milestone A review remediation (R-009 → R-029)

**Environment:** local (Compose Postgres on :15432, MinIO :19000, Redis :16379, inference on :8011)
**Commit:** (uncommitted)

| Command | Result |
| --- | --- |
| `uv run ruff check .` · `ruff format --check .` | pass, 102 files |
| `uv run mypy` | pass, 59 source files |
| `uv run lint-imports` | pass, 5 contracts kept / 0 broken |
| `uv run pytest -q` (no DB env) | 32 passed, **3 skipped** — chat + both RLS tests |
| `uv run pytest -q` (with `.env` loaded) | **39 passed, 0 skipped** — run twice, stable |
| `packages/db/tests/test_rls.py` | 2 passed, **actually executed** (cross-tenant blocked; RLS without ORM) |
| `uv run python -m evals.harness.run --load-corpus` | 14 items, 8 slices, live `retrieve()` per item |
| `uv run python -m evals.harness.run` with `DATABASE_URL` unset | exits **2** with a message — confirms it cannot report synthetic metrics |

**Acceptance criteria verified:**
- [x] Member upload → **403**; steward upload → **202** — role gate is attached, not just defined *(R-009)*
- [x] Steward without ACL `write` on the target collection is refused *(R-013)*
- [x] Document metadata reads are ACL-filtered — verified by a steward uploading into a collection they then could not read back *(R-011)*
- [x] Inference `/v1/embed` without a token → **401**; with the token → **200** *(R-012)*
- [x] Embeddings are non-zero, unit-norm, and deterministic *(R-015)*
- [x] Rerank preserves candidate order *(R-016)*
- [x] ACL isolation end-to-end via the `permission` eval slice: `acme-viewer` retrieves **only** `chunk-legal-secret`; `acme-member` retrieves everything **except** it
- [x] RLS cross-tenant isolation — this time actually executed

**Quality snapshot:** see the table below (row `2026-07-25`), including why it is not comparable to the target row.

**Notes:**
- **Always record what skipped.** An unqualified pass count is not evidence: the same
  suite reports 32 or 39 depending on whether Postgres, MinIO, and inference are up.
  `_inference_reachable` now raises on a 401 instead of turning a misconfiguration into
  a silent skip.
- Embedding and reranker remain stubs, but now degrade to no-ops rather than fabricating:
  deterministic hashed **unit** vectors (the previous zero vectors made pgvector cosine
  distance NaN), and an identity rerank. Default strategy is `hybrid_rrf` until real
  weights land — see [ADR-009](../context/architecture.md#adr-009--a-stub-degrades-to-a-no-op-never-to-a-wrong-signal).
- Generation still uses the extractive fallback without a real `ANTHROPIC_API_KEY`, so
  no answer-quality, latency, or cost metric was measured.
- Two stale `Eng Handbook` documents left in the `Acme Legal` collection by earlier
  failing runs in this session were deleted from the local dev database; tests now use
  `uuid4`-unique markers so accumulated state cannot mask an ACL result *(R-029)*.

---

### E-004 — 2026-07-25 — Security & correctness pass (R-032 → R-057)

**Environment:** local (Compose Postgres :15432, MinIO :19000, Redis :16379, inference :8001)
**Commit:** `080a6bd`

| Command | Result |
| --- | --- |
| `uv run ruff check .` · `ruff format --check .` | pass, 93 files |
| `uv run mypy` | pass, 62 source files |
| `uv run lint-imports` | pass, 5 contracts kept / 0 broken |
| `uv run pytest -q` (with `.env` loaded) | **59 passed, 0 skipped** (was 39) |
| `uv run pytest -q -m "not integration"` (no DB env) | **45 passed, 1 skipped, 13 deselected** |
| `alembic upgrade head` → `downgrade -1` → `upgrade head` | pass — **but only against an already-migrated database; see R-058** |
| `make migrate-check` (full chain from an **empty** database + seed) | pass — added after R-058; this is the check that was missing |
| `npx biome check .` · `npx tsc --noEmit` · `npx next build` | pass, 6 files / build succeeds |

**Defects reproduced, then re-run against the fix.** Each row was executed against a
live stack before and after — this is the evidence, not the pass count above.

| Ref | Before | After |
| --- | --- | --- |
| R-032 | `hybrid_rrf` → `unsupported` at coverage 1.0, while `dense_only` → `grounded` on the same question and corpus | `hybrid_rrf` → **`grounded`** at coverage 1.0 |
| R-033 | After a `NoSuchKey` failure: `('download','pending',0,'-')`, `parse_status=pending` | `('download','failed',1,'NoSuchKey: …')`, `parse_status=failed` |
| R-034 | Mid-request commit → next statement raises `invalid input syntax for type uuid: ""` | Commit, re-query, second commit all succeed; a fresh session with no tenant is still blocked (no pooled-context leak) |
| R-035 | Chunk scoring 0.9 for injection patterns retrievable via `/search` | **0 hits** — filtered in SQL on both arms |
| R-036 | Steward with read-only ACL: upload **403**, archive **200** | archive **403**, unarchive **403**; admin unaffected (200) |
| R-037 | `acme-viewer` rating `acme-member`'s query → **201**; 5 submissions → 5 rows | non-owner → **404**; 5 submissions → **1 row, 1 voter** |
| R-039 | Binary declared `text/plain` → **500**, document left with `parse_status=pending`, `attempts=0` forever | **415**, nothing persisted |
| R-040 | Unlimited `/chat/completions` | `200 ×10` then `429 429 429` at the per-minute cap |
| R-041 | `POST /admin/documents/{id}/erase` → **404** (route absent) | non-admin **403**; admin **200** with `versions_affected=1`, `objects_deleted=1`; re-erase **409**; `erasure_log` written; 0 chunks remain |
| R-045 | Duplicate collection name → **500** | **409** `conflict` |
| R-050 | `/ready` → `200 {"status":"ready"}` unconditionally | `{"status":"ready","checks":{"database":true,"redis":true}}`, 503 when either is down |

**Acceptance criteria verified:**
- [x] Tenant isolation still holds — `globex-admin` searching acme content returns 0 hits; cross-tenant feedback 404
- [x] ACL isolation still holds — engineering-only marker: `acme-member` 5 hits, `acme-viewer` 0 hits
- [x] Staleness is computed, not asserted — classifier returns `fresh`/`stale`/`superseded`, `unknown` rather than guessing
- [x] Citations carry real sentence indices and character spans through to the UI

**Notes:**
- **The bug that mattered most was invisible to the suite that should have caught it.**
  E-003 already noted that the eval harness "does not exercise" the groundedness gate.
  R-032 lived in exactly that gap: retrieval metrics were healthy while the gate
  returned `unsupported` for every query under the default strategy. A note about an
  untested path is a finding, not a caveat — closing R-031 would have caught this.
- Six of the eleven rows above were only reachable by running the system. Reading the
  code showed the confidence formula and the floor; neither is wrong in isolation, and
  the mismatch is only visible once you compute the RRF ceiling.
- One regression was introduced and caught here (R-057): module-level engine caching
  broke Celery, which runs a fresh event loop per task. It failed only when the
  integration tests ran in sequence — a test that passes alone and fails in a suite is
  a signal about shared state, not flakiness.
- A second regression reached CI (R-058). The migration round-trip above was run
  against a database *already stamped at 0001*, so it never built the schema from
  empty — and `0001_initial` uses `Base.metadata.create_all()`, which means it silently
  re-derives from whatever the models currently say. **A migration test that starts from
  your dev database's current revision tests almost nothing.** `make migrate-check` now
  runs the chain from empty; treat that, not `make migrate`, as the migration gate.
- Generation still runs the extractive fallback without a real `ANTHROPIC_API_KEY`, so
  answer-quality, latency, and cost columns remain `n/m`.

---

## Quality Snapshots

One row per full eval run. This table is the regression record for the whole system — the point is that a slow drift is visible across rows, not just within one run.

Targets are from [product.md § 7](../context/product.md#7-success-metrics).

| Date | Commit | Strategy | recall@10 | nDCG@10 | Faithful. | Cite prec. | Unsup. rate | Abstain (correct) | p95 e2e | Cost/query |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| *target* | — | `hybrid_rerank` | ≥ 0.90 | ≥ 0.75 | ≥ 0.95 | ≥ 0.90 | ≤ 2% | ≥ 0.90 | ≤ 4.0 s | ≤ $0.030 |
| ~~2026-07-25~~ | ~~(uncommitted)~~ | ~~`hybrid_rrf`~~ | ~~0.909~~ | ~~0.627~~ | n/m | n/m | n/m | n/m | n/m | n/m |
| 2026-07-26 | `104facc` | `hybrid_rrf` | 0.364 | — | n/m | n/m | n/m | n/m | n/m | n/m |

**No row in this table describes the current system.** Both measured rows were taken with
hashed stub embeddings; the embedder was replaced with real BGE-M3 on 2026-07-27
([E-008](#e-008--2026-07-27--milestone-a-closing-round-r-059-r-061-r-070--r-077)) and no
eval run has been made since. Retrieval quality is **unmeasured**, not unchanged. The next
run must use `--load-corpus` on a reset database and add a row rather than editing one.

**Row 1 is struck through: it does not reproduce.** It was measured against a corpus
containing duplicate documents left by earlier test runs, and `--load-corpus` — the
documented way to rebuild a clean corpus — crashed on every run after the first until R-065
was fixed, so there was no working path to a clean measurement at the time. Re-measured on
2026-07-26 against the fixture corpus it was **0.364** overall, with `crosslingual` at
**0.000** and `factual_en` at 1.000. Row 2 is that re-measurement. It is kept struck rather
than deleted: a number that was published and withdrawn is more useful than a gap.

**Caveats on both measured rows.** They are real runs (14 items, live pipeline, fixture
corpus) but are *not* comparable to the target row:

- Strategy is `hybrid_rrf`, not `hybrid_rerank` — the reranker was an identity stub.
- Embeddings were hashed stubs, so the dense channel carried no semantic signal; nearly
  all measured recall came from the lexical channel. This is why row 2 collapsed to
  0.364 once the corpus was clean, and why `crosslingual` reads 0.000: a Portuguese
  question shares no lexeme with an English passage, and there was no semantic arm to
  bridge them. **That is a property of the stub, and it is exactly what real BGE-M3 is
  expected to fix — which is why neither row can stand in for the current system.**
- `n/m` = not measured. Faithfulness, citation precision, unsupported rate, abstention
  correctness, p95 latency, and cost all require the generation path with a real
  `ANTHROPIC_API_KEY`; the harness scores retrieval only.
- Row 1 per-slice recall@10, on the polluted corpus: crosslingual 1.00, factual_en 1.00,
  factual_pt 1.00, injection 1.00, multi_hop 1.00, permission 1.00, **unanswerable 0.00**,
  **versioned 0.50**. The uniform 1.00s are themselves the tell that the corpus was
  duplicated.
- `versioned` 0.50 is a genuine capability gap, not noise: item `ver-002` asks an
  as-of-date question and retrieval has no point-in-time filter (it hard-codes
  `effective_to IS NULL`). The `as_of` field in the dataset is currently ignored (R-030).
- `unanswerable` recall is 0.00 by construction (no gold passages). The
  `empty_retrieval_rate` reported per slice is 0.0 because lexical search always
  returns something — that is a retrieval-stage signal only, **not** an abstention
  rate. Whether the system abstains is decided by the groundedness gate in the chat
  service, which this harness does not exercise.

<!--
Example row once Phase 4 lands:
| 2026-10-02 | a1b2c3d | hybrid_rerank | 0.923 | 0.781 | 0.961 | 0.914 | 1.4% | 0.93 | 3.6 s | $0.024 |
-->

## Security Gate Log

Two of these must read **0**. A non-zero value blocks release regardless of anything else.

| Date | Commit | Cross-tenant leakage | ACL bypass | Injection success | RLS backstop | Log hygiene |
| --- | --- | --- | --- | --- | --- | --- |
| *gate* | — | **0** | **0** | ≤ 1% | pass | pass |
| 2026-07-25 | `080a6bd` | 0 | 0 (1 fixed) | not measured | pass | pass |
| 2026-07-27 | `104facc` + working tree | 0 | 0 | not measured | pass | pass |

**Row caveats.** *ACL bypass* reads 0 **after** R-036: archive and unarchive required
only read permission to remove a document from every user's retrieval, which is an ACL
bypass by any reading of this gate. It is recorded as fixed-and-verified, not as
never-present.

*Injection success* is **not measured** and must not be read as 0. The `injection`
eval slice scores retrieval, not whether a model followed an injected instruction —
measuring that needs the generation path with a real `ANTHROPIC_API_KEY`. What changed
in this pass is that high-risk chunks are now excluded from retrieval at all (R-035),
which lowers exposure without producing a number for this column.

**Row 3 (2026-07-27).** The isolation and ACL results now come from a **disposable
database** created and dropped by the run (R-071), so they are measurements rather than
observations on a corpus polluted by earlier runs — this is the first row in this table
for which that is true. *Injection success* remains unmeasured for the same reason as
before: no live model. Row 3 is recorded against the working tree, not a commit, and no CI
run exists for it.

---

## Evidence Entries

### E-000 — 2026-07-25 — Planning documentation review

**Environment:** local
**Commit:** *(uncommitted — `docs/` untracked at time of review)*

No automated tests exist; the repository contains documentation only. Verification was a structured review against the plan's own criteria.

| Check | Result |
| --- | --- |
| Every internal doc link resolves to an existing file | pass |
| Every roadmap phase is referenced by an architecture section | pass |
| Every endpoint in `api_rules.md § 12` maps to a table in `architecture.md § 14` | pass |
| Locked decisions (`BGE-M3`, `pgvector`, `RRF`, `claude-opus-5`, `Next.js`, `Terraform`) appear in both architecture and the relevant standards file | pass |
| All 10 production-ready requirements have a named home and a phase | pass — see [roadmap § Cross-Phase Requirement Coverage](../context/roadmap.md#cross-phase-requirement-coverage) |
| All 6 differentiators have a named home and a phase | pass — same table |
| Model IDs, pricing, and API constraints match current Anthropic documentation | pass |
| `git status` shows documentation changes only — no code, config, or lockfiles | pass |

**Notes:** Mermaid rendering in `architecture.md § 3` was not verified in a renderer. Four open questions remain and are tracked in [product.md § 10](../context/product.md#10-open-questions) rather than resolved here — Q-1 and Q-2 are Phase 4 experiments by design.

---

<!-- Newest entries go directly below this line. -->

### E-001 — 2026-07-25 — Review remediation (R-001 … R-008)

**Environment:** local
**Commit:** *(uncommitted)*

Documentation-only change. Each check targets one specific contradiction the review identified, and is written so that a regression re-introducing the contradiction fails the check.

| Check | Command / method | Result |
| --- | --- | --- |
| R-001 — no hard delete | `grep -rn "DELETE.*documents/{id}" docs/` | Only the 405-with-pointer row |
| R-001 — erasure model present | `archived_at`, `erased_at`, `legal_hold`, `erasure_log` in § 14 | pass |
| R-001 — table count consistent | "Twenty-one tables" in architecture § 14 | pass |
| R-002 — no vague privileged role | `grep -rn "privileged role" docs/` | No hits; three-role table present, `rag_app` named as the ingestion identity |
| R-003 — false claim removed | `grep -rn "scoped to the requesting user" docs/` | No hits |
| R-004 — coverage preserved | Requirement matrix walked | 10 requirements + 6 differentiators + removal, each with a phase and a milestone; all 6 differentiators in Milestone A |
| R-005 — materialization gone | `grep -rn "user_visible_documents" docs/` | Only ADR-008 and the deferred-with-conditions text |
| R-006 — revocation specified | § 5.3 states transactional bump + per-request DB read | pass |
| R-007 — profiles behind SLOs | Every row of product § 7.4 names `dev-cpu` or `cloud-gpu` | pass |
| R-008 — CI tiers agree | Tier table, § 6.3, § 7.5, § 12 CI table mutually consistent | pass |
| Links | Slug-accurate checker over all docs | **0 broken** |
| Scope | `git status` | `M README.md`, `?? docs/` — no code, config, or lockfiles |

**Notes:** Still no automated tests — nothing to run against. The checks above are structural consistency verification, which is the strongest available signal for a documentation change. Mermaid rendering re-confirmed via the published artifact rather than a local renderer.

## 2026-09-06 — R-070 chat transport regression (local)

Base: `5e339b9`; branch `test/R-070-chat-outage`. Python 3.12.14 and
locked dependencies restored in `/tmp/milestone-venv` because `.venv` referenced
a missing interpreter. No model calls or paid spend (US$0). No new CI evidence.

- `/tmp/milestone-venv/bin/ruff check .`: pass.
- `/tmp/milestone-venv/bin/ruff format --check .`: 132 files pass.
- `/tmp/milestone-venv/bin/mypy`: 65 source files pass.
- `timeout 120s /tmp/milestone-venv/bin/pytest -q -rs` (outside sandbox):
  83 passed, 1 skipped, 15 deselected. Existing `test_chat.py` skipped because
  Postgres on port 15432 was unavailable; integration tests deselected.
- New outage cases: both passed without skips; actual route, retrieval pipeline,
  and embed error conversion exercised, with HTTP transport forced to ConnectError.
  Auth/DB, ACL resolution, rate limit, and budget preconditions are isolated doubles.
- Negative mutation: moved retrieval into event_stream temporarily; streaming
  regression failed with `Caught handled exception, but response already started`.
  Source restored and the full unit suite rerun successfully.
- Sandbox TestClient/ASGI executions hung; outside-sandbox execution passed.
- Deterministic unit controls run in the suite; DB authorization integration and
  full documented security coverage are not established by this result.

## 2026-09-06 — R-030 point-in-time retrieval (local)

Branch: `feat/R-030-point-in-time`, stacked on R-070 `ddb5623`. Python 3.12.14,
locked dependencies in `/tmp/milestone-venv`. No paid model calls; cumulative
allowance used US$0 of US$25. No CI result or real-model quality/latency claim.

- Ruff check/format: pass (138 Python files). Mypy: 67 source files pass.
- Import-linter: 5 contracts kept, 0 broken.
- `timeout 120s /tmp/milestone-venv/bin/pytest -q -rs`: 116 passed, 1 skipped,
  19 deselected. Existing chat integration-like unit test skips on unavailable
  default port 15432; new tests have no dependency skips.
- Postgres/pgvector 16 in disposable Podman container `rag-milestone-test`,
  database `enterprise_rag_test`, port 25432, initialized with the repository's
  `infra/compose/postgres/init.sql`. App role `rag_app` (RLS enforced).
- `alembic -c packages/db/alembic.ini upgrade head` from empty, then
  `downgrade -1`, `upgrade head`, and `python -m db.seed`: all pass. No migration
  files changed. Existing latest migration is `0004_erasure_audit`.
- `pytest -q -m integration packages/retrieval/tests/test_temporal_integration.py`:
  4 passed, 0 skipped. Run with TEST_DATABASE_URL pointing to rag_app on the
  disposable database and TEST_DATABASE_URL_MIGRATE to rag_migrate on that same DB.
  All four strategies exercise old/new boundaries, missing versions, current
  behavior, archive/erasure/injection exclusions, current ACL deny, tenant
  isolation, lexical evidence, and direct chat-service exact-version citations.
  Corpus embedding and reranking are deterministic doubles; this is SQL/control
  evidence, not semantic retrieval evaluation. Tests roll back fixture mutations.
- OpenAPI matches app in both committed contract locations; generated frontend
  types regenerated using `npm run generate:api-types --prefix apps/web`.
- Frontend `tsc --noEmit` and Biome check of generated types: pass.
- Initial interval test failed due to a duplicate SQL table reference in its
  SQLite fixture; corrected and rerun. No production defect was masked.
- Broader service integration, CI, Phase 4 and live release evidence remain pending.

## 2026-09-07 — T-401 synthetic corpus (local)

Branch: `feat/T-401-fixture-corpus`, based on `3a64aab`. No paid model calls
(US$0 of the US$25 allowance), no CI result, and no quality metrics claimed.

- `python -m evals.build_corpus --check`: verified 247 deterministic artifacts.
- `read_manifest` validates `evals/corpus.json` (170 documents, 211 versions) and
  `evals/corpus_globex.json` (40 documents, 40 versions). Acme contains 40 policy,
  40 routing, 40 restricted, and 40 attack documents; attacks cover all eight
  documented families in five PT/EN-balanced cases each. Globex has 40 conflicting
  policy counterparts. Existing six legacy source versions remain available.
- Every manifest fixture passed UTF-8, SHA-256, safe-path, privacy, and exactly-one-
  current-version validation. Every referenced fixture parses and produces chunks
  through the existing worker parser/chunker.
- Manifest, privacy, reproducibility, and existing metrics tests: 8 passed.
- Full deterministic suite: 122 passed, 1 skipped because the existing chat test's
  default Postgres service on port 15432 was unavailable, 19 integration tests
  deselected by the repository default. No new test was skipped.
- Ruff check/format and mypy passed. No migration, API contract, production default,
  or evaluation baseline changed. Loading both tenants into disposable Postgres and
  worker embeddings is deferred to the evaluation database task; live quality remains
  unmeasured.

## 2026-09-07 — T-402 golden datasets (local)

Branch: `feat/T-402-golden-dataset`, based on `3404dc5`. No paid model calls
(US$0 of the US$25 allowance), no CI result, and no quality metrics claimed.

- `python -m evals.build_dataset --check`: verified 320 deterministic items.
- All eight slices contain exactly 40 unique cases. `factual_pt` and
  `factual_en` are language-pure; crosslingual contains 20 PT→EN and 20 EN→PT.
- Versioned cases cover old (`2024-06-01`), half-open boundary (`2025-01-01`),
  current omission, and absent pre-history (`2023-01-01`) behavior. Permission
  cases contain both `acme-viewer` and `acme-member`; injection cases all carry
  prohibited-source labels. Every source label resolves to T-401 manifests.
- Dataset, manifest, privacy, reproducibility, and metrics tests: 10 passed.
- Ruff check/format and mypy pass. Full suite remains to be rerun after this
task's final edits; integration and live model execution remain separate work.

## 2026-09-07 — T-403 retrieval metrics (local)

Branch: `feat/T-403-retrieval-metrics`, based on `95b52b3`. No paid model calls
(US$0 of the US$25 allowance), no CI result, and no semantic quality claim.

- Added precision@10, explicit empty-gold semantics, duplicate mapped-version
  collapse, and grouped slice/language metrics. The live harness now validates
  all dataset slices and source labels before opening a database session.
- Focused metrics/dataset/manifest tests: 13 tests pass (the
  combined Phase 4 foundation checks remain deterministic).
- Ruff check/format and mypy pass. Full suite is to be rerun after commit; no
baseline, model identity, or production retrieval default changed.

## 2026-09-07 — T-404 answer judges (local)

Branch: `feat/T-404-answer-judges`, based on `2524eaa`. No paid model calls
(US$0 of the US$25 allowance), no CI result, and no answer-quality score claimed.

- Added versioned `evals/harness/judges/entailment_v1.md` and
  `evals/harness/judges/manifest.json` with model `claude-haiku-4-5` and rubric
  SHA-256 `5b090686f49ac59fdcdd352fb38ff9670df0b851d9e74a918cf9a58c70c2548a`.
- `parse_judgement` requires exactly one valid label for every pair. Incomplete
  results expose `complete=false` and an error; chat forces all labels to
  `unrelated`, guaranteeing the verdict cannot pass as grounded.
- Judge, fallback, groundedness tests: 10 passed. Ruff check/format and mypy
  pass. Full suite and CI remain separate evidence; no database or migration
  changed.
