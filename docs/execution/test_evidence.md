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

## Quality Snapshots

One row per full eval run. This table is the regression record for the whole system — the point is that a slow drift is visible across rows, not just within one run.

Targets are from [product.md § 7](../context/product.md#7-success-metrics).

| Date | Commit | Strategy | recall@10 | nDCG@10 | Faithful. | Cite prec. | Unsup. rate | Abstain (correct) | p95 e2e | Cost/query |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| *target* | — | `hybrid_rerank` | ≥ 0.90 | ≥ 0.75 | ≥ 0.95 | ≥ 0.90 | ≤ 2% | ≥ 0.90 | ≤ 4.0 s | ≤ $0.030 |
| 2026-07-25 | (uncommitted) | `hybrid_rrf` | 0.909 | 0.627 | n/m | n/m | n/m | n/m | n/m | n/m |

**Row 1 caveats — read before comparing against target.** Retrieval numbers are real
(14 items, live pipeline, fixture corpus) but are *not* comparable to the target row:

- Strategy is `hybrid_rrf`, not `hybrid_rerank` — the reranker is an identity stub.
- Embeddings are hashed stubs, so the dense channel carries no semantic signal; almost
  all of the measured recall comes from the lexical channel.
- `n/m` = not measured. Faithfulness, citation precision, unsupported rate, abstention
  correctness, p95 latency, and cost all require the generation path with a real
  `ANTHROPIC_API_KEY`; the harness scores retrieval only.
- Per-slice recall@10: crosslingual 1.00, factual_en 1.00, factual_pt 1.00, injection
  1.00, multi_hop 1.00, permission 1.00, **unanswerable 0.00**, **versioned 0.50**.
- `versioned` 0.50 is a genuine capability gap, not noise: item `ver-002` asks an
  as-of-date question and retrieval has no point-in-time filter (it hard-codes
  `effective_to IS NULL`). The `as_of` field in the dataset is currently ignored.
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
| — | — | — | — | — | — | — |

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
