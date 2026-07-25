# Product Context — Enterprise RAG Document Intelligence System

> **Status:** Planning. No code written yet.
> **Related:** [architecture.md](./architecture.md) · [roadmap.md](./roadmap.md)

---

## 1. Problem

Knowledge workers spend a large share of their week hunting for information their organization already owns: policies, contracts, technical documentation, support articles, internal procedures, compliance manuals. The information exists — scattered across file shares, wikis, PDF archives, and email threads, in more than one language, in more than one version, with no reliable way to tell which copy is current or whether the reader is even allowed to see it.

Conventional enterprise search returns *documents*. People need *answers* — with the source attached, so the answer can be trusted and audited.

Generic LLM chat cannot fill this gap: the model has never seen the organization's proprietary documents, has no concept of who may read what, and produces confident text with no traceable origin.

## 2. Value Proposition

Transform a static document repository into an interactive, cited knowledge layer that:

- **Answers in natural language**, in Portuguese or English, grounded in the organization's own documents.
- **Cites every claim** with a link to the exact span in the exact document version it came from.
- **Respects permissions at retrieval time** — a user's answer is composed only from documents that user may read.
- **Refuses to guess.** When the corpus does not support an answer, the system says so instead of improvising.
- **Reports its own quality and cost**, continuously, on a dashboard.

Target outcome: **60–80% reduction in research time** for repeat informational queries, with enterprise-grade security and a complete audit trail.

## 3. Target Industries

| Industry | Representative corpus | Why the fit is strong |
| --- | --- | --- |
| Finance | Credit policies, regulatory circulars, product manuals | High query volume, strict auditability, versions matter |
| Legal | Contracts, precedents, clause libraries | Citation is non-negotiable; versioning is the core problem |
| Insurance | Policy wordings, claims procedures, underwriting rules | Answers must trace to the governing policy version |
| Healthcare | Clinical protocols, formularies, compliance manuals | Freshness is a safety property, not a nicety |
| Consulting | Methodologies, past deliverables, research | Cross-project retrieval; per-client access isolation |
| SaaS | Product docs, runbooks, support articles | Deflects support tickets; bilingual PT/EN user base |
| Government | Regulations, internal procedures, public guidance | Access tiers; bilingual and formal-language corpora |
| Education | Course material, academic policy, admin procedures | Mixed-language corpus; high seasonal query volume |

## 4. Personas

### 4.1 Knowledge Seeker (primary, highest volume)

An analyst, support agent, lawyer, or nurse with a question who needs a trustworthy answer in under a minute.

- **Wants:** a direct answer, the source, and confidence they are seeing everything they are entitled to see.
- **Cannot tolerate:** a fabricated answer, or a stale answer presented as current.
- **Interface:** chat UI with inline citations, source snippets, freshness badges.

### 4.2 Knowledge Steward (curator)

A documentation owner, compliance officer, or team lead responsible for a collection of documents.

- **Wants:** to upload and version documents, see which are going stale, see which questions the corpus answers badly, and fix the gaps.
- **Cannot tolerate:** silent indexing failures, or superseded documents still answering questions.
- **Interface:** admin UI (upload, version history, freshness queue, ingestion job status) plus the eval dashboard's coverage view.

### 4.3 Platform Admin (operator)

The person running the deployment for one or many tenants.

- **Wants:** tenant provisioning, role and group management, per-tenant cost and quota visibility, and evidence that tenant isolation actually holds.
- **Cannot tolerate:** cross-tenant leakage, or an unbounded cost surprise.
- **Interface:** admin UI (tenants, roles, quotas, cost) plus metrics and traces.

## 5. Scope

Scope is delivered in two milestones — see [roadmap.md § Two release boundaries](./roadmap.md#two-release-boundaries). **Milestone A (Portfolio release)** is a complete, deployable system carrying all six differentiators; **Milestone B (Enterprise expansion)** adds breadth. The list below is the full v1 surface; the milestone column says when.

### 5.1 In scope (v1)

**Ingestion & content**

- Multi-tenant document ingestion — **A:** PDF, Markdown, plain text · **B:** DOCX, HTML, EML
- Scanned/image PDFs via OCR — **B**
- Document versioning with content hashing and supersession chains — **A**
- Archival, and privileged erasure for legal/privacy requests — **A**
- Document freshness detection and review scheduling — **B**

**Retrieval**

- Hybrid retrieval: dense semantic (pgvector) + lexical full-text (Postgres FTS), fused with Reciprocal Rank Fusion
- Cross-encoder reranking
- Permission-aware **pre-filtered** retrieval (ACL applied before ranking, not after)
- Cross-lingual PT↔EN retrieval (a Portuguese question retrieves relevant English documents and vice versa) — **A**

**Generation**

- Cited answers using Anthropic native document citations (character-level spans)
- Streaming responses
- Automated unsupported-answer detection with abstention
- Layered prompt-injection defense

**Platform**

- Role-based access control per collection and per document
- Tenant isolation enforced at both the application layer and the database layer
- Per-query cost tracking — **A** · per-tenant budgets and quotas — **B**
- Retry, timeout, circuit-breaker, and model-fallback policies — **B**
- Evaluation datasets, an offline evaluation harness, and a retrieval-strategy comparison
- Feedback loop (thumbs up/down + reason) feeding the evaluation corpus

**Interfaces**

- Chat UI with citations — **A**
- Document admin (upload, jobs, versions) — **A**
- Evaluation dashboard — **B**
- Full admin UI (tenants, roles, quotas, cost) — **B**
- Versioned REST API with OpenAPI

### 5.2 Out of scope (v1)

See [roadmap.md § Deferred](./roadmap.md#10-deferred--vnext).

- Live connector sync (SharePoint, Google Drive, Confluence, S3 watch)
- Model fine-tuning or embedding-model training
- Agentic multi-hop research loops beyond single-turn retrieval plus tool calls
- Voice or telephony interfaces
- Write-back to source systems (the assistant reads; it never edits source documents)
- Real-time collaborative editing
- Air-gapped deployment (the LLM call requires network egress)

## 6. Differentiators vs. Tutorial RAG

The market is saturated with "chat with your PDF" demos. Six capabilities separate this system from them, and each is a first-class deliverable, not a stretch goal:

| # | Differentiator | Why tutorials skip it | Where it lives |
| --- | --- | --- | --- |
| 1 | **Permission-aware retrieval** | Requires ACL resolution inside the ranking query; post-filtering is easier and wrong | [architecture.md § 7](./architecture.md#7-retrieval-pipeline) |
| 2 | **Evaluation dashboard** | Requires a labelled golden set and a metrics harness | [architecture.md § 11](./architecture.md#11-evaluation-architecture) |
| 3 | **Document freshness detection** | Requires versioning and supersession modelling | [architecture.md § 6](./architecture.md#6-document-versioning--freshness) |
| 4 | **Multilingual PT↔EN retrieval** | Requires a multilingual embedding model and dual-config full-text indexing | [architecture.md § 7](./architecture.md#7-retrieval-pipeline) |
| 5 | **Retrieval-strategy comparison** | Requires the pipeline to be swappable and measurable | [architecture.md § 11](./architecture.md#11-evaluation-architecture) |
| 6 | **Automated unsupported-answer detection** | Requires citation-coverage analysis plus a judge model | [architecture.md § 10](./architecture.md#10-groundedness--unsupported-answer-detection) |

## 7. Success Metrics

Measured on the golden evaluation set (bilingual, versioned, committed to the repo) unless noted.

### 7.1 Retrieval quality

| Metric | Target | Notes |
| --- | --- | --- |
| `recall@10` | ≥ 0.90 | Fraction of questions where a gold-relevant chunk is in the top 10 after fusion |
| `recall@50` | ≥ 0.97 | Ceiling on what reranking can recover |
| `nDCG@10` | ≥ 0.75 | Post-rerank ranking quality |
| `MRR@10` | ≥ 0.70 | How high the first relevant result lands |
| Cross-lingual `recall@10` | ≥ 0.85 | PT question → EN gold document, and the reverse |

### 7.2 Answer quality

| Metric | Target | Notes |
| --- | --- | --- |
| Faithfulness | ≥ 0.95 | Every claim entailed by its cited span |
| Citation precision | ≥ 0.90 | Cited span actually supports the claim attached to it |
| Answer relevance | ≥ 0.85 | Answer addresses the question asked |
| Unsupported-answer rate | ≤ 2% | Answers emitted without adequate grounding |
| Correct abstention rate | ≥ 0.90 | On the "unanswerable" slice of the golden set, the system declines |

### 7.3 Security

| Metric | Target | Notes |
| --- | --- | --- |
| Cross-tenant leakage | **0** | Hard gate. Any occurrence blocks release. |
| ACL bypass | **0** | Hard gate. Includes the RLS-only test with ORM filters removed. |
| Prompt-injection success rate | ≤ 1% | On the adversarial injection suite |

### 7.4 Performance & cost

A latency target without a workload behind it can be met by shrinking the corpus, dropping concurrency, or measuring a warm cache. Two **benchmark profiles** are therefore normative, and every target below names one. A measurement that does not state its profile is not a result.

| Parameter | `dev-cpu` | `cloud-gpu` |
| --- | --- | --- |
| Environment | Docker Compose, one host | ECS Fargate, one region |
| Inference hardware | CPU (4 vCPU) | GPU-backed `inference` task |
| Corpus | 10k chunks, 1 tenant | 100k chunks, 2 tenants |
| Concurrency | 1 user | 20 concurrent users |
| `max_tokens` | 2048 | 2048 |
| Retrieved context | 8 chunks, ~6k tokens | 8 chunks, ~6k tokens |
| Cache state | Warm (prompt cache primed) | Warm |
| Model | `claude-opus-5`, primary path | `claude-opus-5`, primary path |
| Network | Loopback | Same-region, client in-region |

Cold starts, fallback-model paths, and OCR ingestion are measured and recorded but **not** gated — they are reported alongside, never substituted for, the warm primary-path number.

| Metric | `dev-cpu` | `cloud-gpu` | Notes |
| --- | --- | --- | --- |
| Time to first token (p95) | ≤ 2.5 s | ≤ 1.2 s | Streamed chat |
| End-to-end answer (p95) | ≤ 6 s | ≤ 4 s | Retrieval + rerank + generation |
| Retrieval-only latency (p95) | ≤ 900 ms | ≤ 400 ms | Hybrid + rerank, excludes the LLM |
| — of which reranking | ≤ 450 ms | ≤ 80 ms | Cross-encoder over 50 candidates |
| Ingestion throughput | ≥ 25 pages/min/worker | ≥ 100 pages/min/worker | Text PDFs; OCR measured separately |
| Cost per query (median) | ≤ US$ 0.03 | ≤ US$ 0.03 | Hardware-independent |
| Prompt cache hit rate | ≥ 0.70 | ≥ 0.70 | Hardware-independent |

The `dev-cpu` numbers are looser for one specific reason: BGE-reranker-v2-m3 on CPU needs roughly 200–450 ms to score 50 candidates, which alone consumes the entire `cloud-gpu` retrieval budget before generation starts. Publishing the tight numbers as universal would mean every local measurement failed an SLO the environment was never capable of meeting — so the profile that developers actually run against is stated honestly rather than aspirationally.

## 8. User Stories

Phase column refers to [roadmap.md](./roadmap.md).

### Knowledge Seeker

| ID | Story | Phase |
| --- | --- | --- |
| KS-1 | I ask a question in Portuguese and get an answer grounded in our documents, even when the source is in English. | 3 |
| KS-2 | Every statement in the answer carries a citation I can click to see the exact source passage. | 3 |
| KS-3 | When the corpus does not support an answer, the system tells me so rather than guessing. | 3 |
| KS-4 | I see a freshness indicator on each cited source so I know whether it is current. | 5 |
| KS-5 | I never see content from a document I am not authorized to read — including in summaries or result counts. | 2 |
| KS-6 | The answer starts streaming quickly rather than appearing all at once after a long wait. | 3 |
| KS-7 | I can mark an answer as good or bad and say why, and that feedback is recorded. | 6 |

### Knowledge Steward

| ID | Story | Phase |
| --- | --- | --- |
| KW-1 | I upload a document and watch its ingestion job progress through parse, chunk, embed, and index. | 1 |
| KW-2 | When I upload a new version, the old one is superseded and stops answering "current" questions. | 1 |
| KW-3 | I see a queue of documents past their review interval or otherwise going stale. | 5 |
| KW-4 | I set which roles and groups can read each collection and each document. | 2 |
| KW-5 | I see which questions the corpus answers badly so I know what to write next. | 4 |
| KW-6 | A failed ingestion is visible with a readable error, not silently dropped. | 1 |

### Platform Admin

| ID | Story | Phase |
| --- | --- | --- |
| PA-1 | I provision a tenant and its data is isolated from every other tenant at the database level. | 0 |
| PA-2 | I see per-tenant query volume, token spend, and cost, broken down by model. | 5 |
| PA-3 | I set a monthly budget per tenant with a soft warning and a hard stop. | 5 |
| PA-4 | I compare retrieval strategies side by side on the golden set before changing the default. | 4 |
| PA-5 | When the primary model is unavailable or refuses, the system degrades gracefully instead of erroring. | 5 |
| PA-6 | I can trace a single query end-to-end across services to diagnose latency. | 5 |

## 9. Non-Functional Requirements

| Category | Requirement |
| --- | --- |
| Availability | Single-region; graceful degradation when the LLM provider is unavailable |
| Data residency | Document content and embeddings stay in the deployment's own storage. Only the retrieved context for a single query transits to the LLM provider. |
| Retention | Query logs and citations retained 90 days by default, configurable per tenant |
| Privacy | No document content in application logs. PII scanning on the egress path. |
| Auditability | Every answer reconstructable: query, retrieved chunk IDs, document version IDs, model, prompt hash, cost |
| Portability | No managed vector-database lock-in. Postgres is the only stateful store for search. |
| Localization | UI and system prompts in PT-BR and EN |

## 10. Open Questions

Tracked here until resolved; each becomes an ADR in [architecture.md § 15](./architecture.md#15-architecture-decision-records) when decided.

| # | Question | Owner | Blocking? |
| --- | --- | --- | --- |
| Q-1 | Chunking default — fixed-token with overlap vs. layout-aware semantic sectioning | Eng | No — Phase 1 ships fixed-token, Phase 4 measures |
| Q-2 | Whether to expose BGE-M3's sparse vectors as a third retrieval arm alongside Postgres FTS | Eng | No — Phase 4 experiment |
| Q-3 | Conversation memory depth for multi-turn chat (last N turns vs. summarized) | Product | No — Phase 3 ships last-3-turns |
| Q-4 | Whether the eval dashboard is admin-only or also visible to Stewards | Product | No — Phase 6 |
