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
