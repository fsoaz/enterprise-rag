# Roadmap — Enterprise RAG Document Intelligence System

> **Status:** Planning. Phase 0 not started.
> **Related:** [product.md](./product.md) · [architecture.md](./architecture.md) · [../tasks/README.md](../tasks/README.md)

---

## How to read this

Phases are **dependency-ordered, not calendar-scheduled**. Each phase lists its goal, deliverables, exit criteria, and the user stories it satisfies. A phase is done when every exit criterion is demonstrably met and recorded in [test_evidence.md](../execution/test_evidence.md) — not when the code merges.

Task IDs follow `T-<phase><seq>` (see [tasks/README.md](../tasks/README.md)). Size is a rough relative indicator: **S** ≈ a day, **M** ≈ a few days, **L** ≈ a week or more.

| Phase | Theme | Size | Unlocks |
| --- | --- | --- | --- |
| [0](#phase-0--foundation) | Foundation | M | Everything |
| [1](#phase-1--ingestion--versioning) | Ingestion & versioning | L | A corpus to search |
| [2](#phase-2--retrieval-core) | Retrieval core | L | Permission-aware search |
| [3](#phase-3--generation--citations) | Generation & citations | L | Answers |
| [4](#phase-4--evaluation) | Evaluation | M | Evidence that it works |
| [5](#phase-5--operations) | Operations | M | Production readiness |
| [6](#phase-6--user-interfaces) | User interfaces | L | Demonstrability |
| [7](#phase-7--cloud--hardening) | Cloud & hardening | M | Deployment |

---

## Phase 0 — Foundation

**Goal:** A running skeleton with tenancy and auth proven before any feature is built on top of them.

### Deliverables

- Monorepo scaffold per [architecture.md § 16](./architecture.md#16-repository-layout)
- Docker Compose stack: Postgres 16 + pgvector, Redis, MinIO, Keycloak
- FastAPI `api` service with health/ready endpoints and OpenAPI generation
- Celery `worker` service with a no-op task, proving broker wiring
- `inference` service skeleton returning stub vectors (real models land in Phase 1)
- Alembic wired; initial migration creating `tenants`, `users`, `groups`, `user_groups`, `roles`
- **Row-Level Security enabled and policies written** for every tenant-scoped table
- OIDC/JWT auth: JWKS verification, tenant context dependency, `SET LOCAL app.current_tenant` per transaction
- CI: lint (`ruff`, `biome`), typecheck (`mypy`, `tsc`), unit tests, migration up/down check
- `make up` seeds two demo tenants with distinct users and groups

### Exit criteria

- [ ] `make up` produces a working stack from a clean clone in under 5 minutes
- [ ] A request with tenant A's token cannot read tenant B's rows — proven by a test
- [ ] The **same test passes with the ORM tenant filter deliberately removed** (RLS backstop works)
- [ ] `alembic upgrade head` and `alembic downgrade -1` both succeed in CI
- [ ] OpenAPI schema is generated and committed

**Stories:** PA-1

**Tasks:** `T-001` scaffold · `T-002` compose stack · `T-003` migrations + RLS · `T-004` auth & tenant context · `T-005` CI pipeline · `T-006` seed data

---

## Phase 1 — Ingestion & Versioning

**Goal:** Documents get into the system, become searchable chunks, and carry a version history.

### Deliverables

- `POST /api/v1/documents` upload → S3/MinIO → `202 Accepted` + job resource
- Ingestion pipeline in `worker`, one Celery task per stage with independent retries:
  `download → parse → ocr (conditional) → chunk → embed → index`
- Parsers: PDF, DOCX, HTML, Markdown, plain text, EML
- OCR path for image-only PDFs
- Chunking: fixed-token with overlap (default 512 tokens / 64 overlap), section-path metadata preserved
- **Real BGE-M3** in `inference`, with correct `query` vs. `passage` instruction prefixes
- `chunk_embeddings` written with `model_name` + `model_version`
- `chunks.search_vector` generated with dual `portuguese` + `english` FTS configs
- HNSW and GIN indexes created
- Versioning: `content_sha256` dedupe, `supersedes_id` chain, `effective_from` / `effective_to`, partial unique index enforcing one current version
- Job status endpoint with per-stage progress and readable errors
- Ingestion-time injection heuristic scoring `chunks.injection_risk`

### Exit criteria

- [ ] A 50-page bilingual PDF ingests end to end and produces queryable chunks
- [ ] Re-uploading identical bytes is a no-op (no duplicate version)
- [ ] Uploading a modified file creates v2 and marks v1 superseded, with v1's chunks retained
- [ ] A corrupt file produces a `failed` job with a readable error, not a silent drop
- [ ] Ingestion throughput ≥ 100 pages/min/worker on text PDFs
- [ ] Every chunk carries `tenant_id`, `document_version_id`, `language`, and a populated `search_vector`

**Stories:** KW-1, KW-2, KW-6

**Tasks:** `T-101` upload endpoint + object storage · `T-102` parser suite · `T-103` OCR path · `T-104` chunker · `T-105` BGE-M3 in inference · `T-106` embed + index stage · `T-107` version chain + supersession · `T-108` job status API · `T-109` injection heuristic

---

## Phase 2 — Retrieval Core

**Goal:** Hybrid, reranked, permission-aware search. This phase contains the system's most important correctness property.

### Deliverables

- ACL model: `acl_entries`, `acl_versions`, resolution order (document deny → document allow → collection deny → collection allow → default deny)
- ACL → SQL predicate compiler, with the `IN (...)` vs. materialized-join switch by cardinality
- Redis-cached compiled predicate, invalidated by `acl_version` bump
- Dense arm: pgvector HNSW cosine, top-50, under the ACL + tenant + current-version predicate
- Lexical arm: Postgres FTS `ts_rank_cd`, top-50, same predicate
- RRF fusion (`k = 60`) as a single SQL statement with both arms as CTEs
- **BGE-reranker-v2-m3** in `inference`; batched rerank of top-50 → top-8
- `ef_search` tuning and the low-cardinality exact-search fallback
- Context assembly with token budget and adjacent-chunk merging
- Strategy interface: `dense_only`, `lexical_only`, `hybrid_rrf`, `hybrid_rerank`
- `POST /api/v1/search` returning ranked chunks with scores and provenance
- Collection and document ACL management endpoints

### Exit criteria

- [ ] `recall@10 ≥ 0.90` on the Phase 4 golden set precursor (a manually built 50-item set is acceptable here)
- [ ] Cross-lingual retrieval works: a PT query surfaces a relevant EN document
- [ ] **Two users with different ACLs get provably different result sets for the same query**
- [ ] A user with access to 5% of the corpus still gets a full top-8 (pre-filtering, not post-filtering — verified by a test that counts results)
- [ ] Result counts do not leak the existence of inaccessible documents
- [ ] Retrieval-only p95 ≤ 400 ms on a 100k-chunk corpus
- [ ] Reranking measurably improves `nDCG@10` over `hybrid_rrf` alone

**Stories:** KS-5, KW-4

**Tasks:** `T-201` ACL model + migration · `T-202` predicate compiler + cache · `T-203` dense arm · `T-204` lexical arm · `T-205` RRF fusion SQL · `T-206` reranker in inference · `T-207` rerank stage · `T-208` context assembly · `T-209` `/search` endpoint · `T-210` ACL management API · `T-211` HNSW tuning + fallback

---

## Phase 3 — Generation & Citations

**Goal:** Cited, streamed, grounded answers with injection defense.

### Deliverables

- Anthropic client wrapper in `packages/llm`: model registry, adaptive thinking, streaming, retries, `stop_reason` handling, server-side `fallbacks: "default"`
- Prompt assembly: cached stable system + tenant policy prefix, retrieved chunks as separate `document` blocks with `citations: {enabled: true}`
- Citation mapping: `document_index` → `chunk_id` → `document_version_id`, persisted to `query_citations`
- `POST /api/v1/chat/completions` with SSE streaming (`token`, `citation`, `usage`, `done`, `error`)
- Multi-turn context (last 3 turns, per Q-3)
- Read-only tool calling: `search_documents`, `get_document_metadata`, both ACL-bound, capped at 3 calls
- Prompt-injection defense layers: structural placement, instruction hierarchy in the system prompt, mid-conversation `role: "system"` operator channel, tool allowlist, egress scan
- Groundedness: citation coverage + Haiku entailment judge + retrieval confidence → verdict
- Abstention path with closest-sources fallback
- Prompt cache verification via `usage.cache_read_input_tokens`

### Exit criteria

- [ ] Every answer sentence carries a resolvable citation, or the answer is marked `partial`/`unsupported`
- [ ] A citation resolves to a real character span in a real document version
- [ ] Time to first token p95 ≤ 1.2 s
- [ ] On the `unanswerable` slice, the system abstains rather than inventing an answer
- [ ] A document containing "ignore previous instructions…" does not alter system behavior
- [ ] Prompt cache hit rate ≥ 0.70 across repeated queries in one tenant
- [ ] `stop_reason == "refusal"` is handled without a crash or an empty-content indexing error

**Stories:** KS-1, KS-2, KS-3, KS-6

**Tasks:** `T-301` Anthropic client wrapper · `T-302` prompt assembly + caching · `T-303` native citations + mapping · `T-304` SSE chat endpoint · `T-305` multi-turn context · `T-306` tool calling · `T-307` injection defense layers · `T-308` groundedness signals · `T-309` abstention path · `T-310` egress scan

---

## Phase 4 — Evaluation

**Goal:** Evidence. Every quality claim in [product.md § 7](./product.md#7-success-metrics) becomes a measured number.

### Deliverables

- Golden dataset in `evals/datasets/`, all eight slices (`factual_pt`, `factual_en`, `crosslingual`, `multi_hop`, `versioned`, `unanswerable`, `permission`, `injection`), minimum 40 items per slice
- Synthetic bilingual fixture corpus in `evals/fixtures/` — no real customer data
- Metrics harness: retrieval (`recall@k`, `precision@k`, `nDCG@10`, `MRR@10`), answer (faithfulness, citation precision/recall, relevance), safety, behavior, ops
- Haiku-based judges with **versioned rubric prompts**; `judge_prompt_hash` stored on every run
- `eval_datasets` / `eval_items` / `eval_runs` / `eval_results` tables and API
- Strategy comparison runner: sweeps strategy × embedding model × reranker × params
- CI integration: smoke subset per PR with regression gates; nightly full run
- **Experiments resolving open questions:** Q-1 (chunking strategy), Q-2 (BGE-M3 sparse as a third arm), plus query expansion cost/benefit

### Exit criteria

- [ ] Full eval run completes and writes results for every slice
- [ ] The strategy comparison produces a matrix with per-slice deltas
- [ ] `hybrid_rerank` is demonstrably the best default, with numbers
- [ ] A deliberate retrieval regression is caught by the PR gate
- [ ] Cross-tenant leakage and ACL bypass both measure **0** on the `permission` slice
- [ ] Injection success rate ≤ 1% on the `injection` slice
- [ ] Q-1 and Q-2 are decided and recorded as ADRs in [architecture.md § 15](./architecture.md#15-architecture-decision-records)

**Stories:** KW-5, PA-4

**Tasks:** `T-401` fixture corpus · `T-402` golden dataset authoring · `T-403` retrieval metrics · `T-404` answer-quality judges · `T-405` eval tables + API · `T-406` strategy comparison runner · `T-407` CI gates · `T-408` chunking experiment (Q-1) · `T-409` sparse-arm experiment (Q-2)

---

## Phase 5 — Operations

**Goal:** The system can be run, paid for, and diagnosed.

### Deliverables

- `cost_ledger` + versioned `model_prices`; a row per LLM call with no exceptions
- Per-tenant and per-user rate limits (Redis token bucket) with `RateLimit-*` headers
- Monthly USD budgets: soft warning at 80%, hard stop at 100%, admin override
- OpenTelemetry tracing across all four services, with spans per retrieval stage
- `structlog` JSON logging with `request_id` / `tenant_id` / `user_id`, and a test asserting no document content is logged
- Prometheus metrics per [architecture.md § 12.3](./architecture.md#123-observability)
- Timeout table, `tenacity` retries with jitter, circuit breakers per dependency
- Degradation ladder implemented and each rung individually testable
- Freshness: nightly `staleness_score` recomputation, review queue, freshness badge data on citations
- Conflict detection between similar current versions

### Exit criteria

- [ ] Every LLM call in the system produces a `cost_ledger` row — verified by a test that counts calls vs. rows
- [ ] Cost per query is visible per tenant, broken down by model and purpose
- [ ] A tenant at 100% of budget receives a 429 with the correct problem type
- [ ] Killing `inference` degrades to lexical-only retrieval instead of erroring
- [ ] Killing the Anthropic dependency degrades to extractive answers instead of erroring
- [ ] A single query is traceable end-to-end across all four services
- [ ] The staleness queue correctly surfaces overdue documents
- [ ] No document content appears in any log line

**Stories:** KS-4, PA-2, PA-3, PA-5, PA-6

**Tasks:** `T-501` cost ledger + price table · `T-502` rate limits · `T-503` budgets + enforcement · `T-504` OTel tracing · `T-505` structured logging · `T-506` Prometheus metrics · `T-507` retries + timeouts + breakers · `T-508` degradation ladder · `T-509` freshness job + queue · `T-510` conflict detection

---

## Phase 6 — User Interfaces

**Goal:** Three UIs in one Next.js app. This is what makes the system demonstrable.

### Deliverables

**Chat (`app/(chat)`)**
- Streaming answers via SSE
- Inline citation chips; click opens a source panel with the cited span highlighted in context
- Freshness badge and version label per source
- Groundedness banner for `partial` answers; distinct abstention state
- Language toggle (PT-BR / EN)
- Feedback: thumbs up/down + reason code + optional comment

**Eval dashboard (`app/(eval)`)**
- Run list with strategy, dataset version, git SHA, judge prompt hash
- Metric cards per slice; trend chart across runs
- **Strategy comparison matrix** with per-slice deltas and significance flags
- Per-item drill-down: question, retrieved chunks with scores, answer, verdict, cost
- Failure explorer filtered by slice and verdict

**Admin (`app/(admin)`)**
- Document upload with drag-and-drop and live job status
- Document list with version history and supersession chain
- Freshness / review queue
- Collection, group, and role management; ACL editor
- Tenant list, quota and budget configuration
- Cost view: spend by tenant, model, and purpose over time

### Exit criteria

- [ ] A user can ask a question, watch it stream, click a citation, and see the highlighted source span
- [ ] Abstention renders as a distinct, non-alarming state — not an error
- [ ] The strategy comparison matrix renders real eval data
- [ ] A Steward can upload a document and follow its job to completion without a page reload
- [ ] An Admin can change an ACL and see the effect on the next query immediately (cache invalidation works)
- [ ] Accessible: keyboard navigation, focus management on the streaming region, `prefers-color-scheme` support
- [ ] Playwright e2e covers the three primary flows

**Stories:** KS-7, KW-3, plus the UI surface for every prior story

**Tasks:** `T-601` Next.js scaffold + auth · `T-602` chat UI + SSE · `T-603` citation panel · `T-604` feedback · `T-605` eval dashboard · `T-606` comparison matrix · `T-607` admin upload + jobs · `T-608` version history UI · `T-609` ACL editor · `T-610` cost & quota views · `T-611` e2e tests

---

## Phase 7 — Cloud & Hardening

**Goal:** Deployed, load-tested, and reviewed.

### Deliverables

- Terraform modules: VPC, ECS Fargate services ×4, ALB + ACM, RDS Postgres 16 with pgvector, ElastiCache Redis, S3 with per-tenant prefix policy, Secrets Manager, Cognito, ECR
- Remote state in S3 with DynamoDB locking
- CI/CD: build → push to ECR → auto-deploy to staging → manual promotion of the same digest to production
- Expand/contract migration discipline enforced in the deploy task
- k6 load-test scenarios against staging with the SLO targets from [product.md § 7.4](./product.md#74-performance--cost)
- Security review: `/security-review` on the full diff, dependency audit, secret scanning, S3 and IAM least-privilege check
- Backup and restore drill for RDS, executed and documented
- Runbook: common failures, degradation modes, how to read the dashboards

### Exit criteria

- [ ] `terraform apply` builds the full stack from scratch in a clean AWS account
- [ ] Staging deploy is fully automated on merge to `main`
- [ ] Production promotion deploys the exact image digest that passed staging
- [ ] Load test sustains target p95 at expected concurrency
- [ ] A restore from backup is executed and the resulting system passes the smoke eval
- [ ] Security review produces no unresolved high-severity findings
- [ ] Runbook exists and a cold reader can follow it

**Stories:** operational support for all

**Tasks:** `T-701` Terraform network + data · `T-702` Terraform services + ALB · `T-703` secrets + auth · `T-704` CI/CD pipeline · `T-705` migration deploy task · `T-706` k6 load tests · `T-707` security review · `T-708` backup/restore drill · `T-709` runbook

---

## 10. Deferred / vNext

Explicitly not in v1. Listed so the boundary is a decision, not an oversight.

| Item | Why deferred | Would require |
| --- | --- | --- |
| Live connector sync (SharePoint, Drive, Confluence, S3 watch) | Each connector is its own auth, pagination, and change-detection problem | A connector framework + per-source incremental sync |
| Agentic multi-hop research | Single-turn retrieval plus 3 tool calls covers the target queries; multi-hop multiplies cost and latency | A planner loop with budget control |
| Fine-tuned domain reranker | Needs production click/feedback data that does not exist yet | Training pipeline + labelled pairs from `feedback` |
| GraphRAG / entity graph | Large complexity for gains the golden set has not yet shown are needed | Entity extraction, graph store, graph-aware retrieval |
| OpenSearch lexical arm | See [ADR-003](./architecture.md#adr-003--postgres-fts-over-opensearch) | An implementation behind the existing `KeywordSearch` interface |
| Per-tenant embedding models | No demonstrated need; multiplies index and ops cost | Per-tenant model registry, isolated index generations |
| Multi-region / active-active | Single region meets the availability target | Cross-region replication, conflict handling |
| Air-gapped deployment | The LLM call requires egress | A self-hosted generation model |
| Voice interface | Out of product scope | STT/TTS pipeline |
| Answer caching across users | Cross-user cache and per-user ACL are in direct tension; the safe version is per-(user, query) and low-value | ACL-aware cache keying with revocation |

---

## Cross-Phase Requirement Coverage

Every production-ready requirement from the project brief, mapped to where it is built.

| Requirement | Phase | Section |
| --- | --- | --- |
| Document ingestion and versioning | 1 | [architecture § 6](./architecture.md#6-document-versioning--freshness) |
| Role-based access control | 2 | [architecture § 5](./architecture.md#5-access-control-model) |
| Hybrid semantic + keyword retrieval | 2 | [architecture § 7](./architecture.md#7-retrieval-pipeline) |
| Reranking | 2 | [architecture § 7.7](./architecture.md#77-stage-6--reranking) |
| Source citations | 3 | [architecture § 8.3](./architecture.md#83-native-citations) |
| Evaluation datasets | 4 | [architecture § 11](./architecture.md#11-evaluation-architecture) |
| Prompt-injection protection | 3 | [architecture § 9](./architecture.md#9-prompt-injection-defense) |
| Query and cost monitoring | 5 | [architecture § 12](./architecture.md#12-cost-quotas--observability) |
| Tenant isolation | 0 | [architecture § 4](./architecture.md#4-multi-tenancy--isolation) |
| Retry, timeout, fallback policies | 5 | [architecture § 13](./architecture.md#13-resilience-policies) |
| **Differentiator:** permission-aware retrieval | 2 | [architecture § 5.4](./architecture.md#54-why-post-filtering-is-wrong) |
| **Differentiator:** evaluation dashboard | 4 + 6 | [architecture § 11.3](./architecture.md#113-strategy-comparison) |
| **Differentiator:** freshness detection | 1 + 5 | [architecture § 6.2](./architecture.md#62-freshness-signals) |
| **Differentiator:** multilingual PT↔EN | 1 + 2 | [architecture § 7.5](./architecture.md#75-stage-4b--lexical-retrieval) |
| **Differentiator:** strategy comparison | 4 | [architecture § 11.3](./architecture.md#113-strategy-comparison) |
| **Differentiator:** unsupported-answer detection | 3 | [architecture § 10](./architecture.md#10-groundedness--unsupported-answer-detection) |
