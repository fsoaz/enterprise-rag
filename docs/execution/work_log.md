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
