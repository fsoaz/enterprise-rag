# enterprise-rag

**Enterprise RAG Document Intelligence System** — turn a static document repository into an interactive, cited knowledge layer with permission-aware retrieval, multilingual PT↔EN search, and measured answer quality.

> **Status: Milestone A MVP implemented.** Compose + API + retrieval + chat UI. Inference stubs and extractive LLM fallback work without GPU/API keys; set `ANTHROPIC_API_KEY` and real BGE weights for production-quality answers.

---

## What this is

Employees waste hours searching policies, contracts, technical documentation, and internal procedures. Conventional search returns documents; people need answers — with the source attached, so the answer can be trusted and audited.

This system answers questions in Portuguese or English, grounded in an organization's own documents, with a citation on every claim pointing at the exact span in the exact document version it came from. It respects per-document permissions *at retrieval time*, detects when documents are going stale, refuses to answer when the corpus does not support one, and reports its own quality and cost on a dashboard.

## Stack

| Layer | Choice |
| --- | --- |
| API | Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) |
| Search | PostgreSQL 16 + pgvector (HNSW) + Postgres FTS (`portuguese` / `english`), fused with RRF |
| Embeddings | BGE-M3, self-hosted — 1024-dim, multilingual |
| Reranking | BGE-reranker-v2-m3, self-hosted cross-encoder |
| Generation | Anthropic Claude — `claude-opus-5` primary, `claude-haiku-4-5` for judging |
| Jobs / cache | Celery + Redis |
| Storage | MinIO (dev) / S3 (cloud) |
| Frontend | Next.js (App Router) · TypeScript · shadcn/ui |
| Deploy | Docker Compose (dev) · Terraform → AWS ECS Fargate (cloud) |

No orchestration framework, no managed vector database. Both are deliberate — see [ADR-001](docs/context/architecture.md#adr-001--no-orchestration-framework) and [ADR-002](docs/context/architecture.md#adr-002--postgres-only-search).

## What makes it different from a tutorial

| | |
| --- | --- |
| **Permission-aware retrieval** | ACLs are compiled into the ranking query, not applied afterwards. Post-filtering silently collapses recall and leaks result counts. |
| **Native citations** | Character-level spans returned by the API, not `[1]`/`[2]` markers the model could invent. |
| **Unsupported-answer detection** | Citation coverage + an entailment judge + retrieval confidence. Below threshold, the system abstains. |
| **Evaluation dashboard** | Eight-slice bilingual golden set, measured every night, gated in CI. |
| **Retrieval-strategy comparison** | "Hybrid + rerank is better" is a number on a dashboard, not an assertion in a README. |
| **Freshness detection** | Chunks belong to document *versions*, so supersession is metadata and old citations stay resolvable. |

## Architecture at a glance

```text
Next.js web ──▶ FastAPI api ──┬──▶ Postgres 16 + pgvector + FTS + RLS
                              ├──▶ Redis (cache · queue · limits)
                              ├──▶ S3 / MinIO (original files)
                              ├──▶ inference (BGE-M3 · BGE-reranker-v2-m3)
                              └──▶ Anthropic API
                                       ▲
              Celery worker ───────────┘  (ingest · reindex · freshness)
```

Full diagram and component contracts: [architecture.md § 3](docs/context/architecture.md#3-component-topology).

## Documentation

### Context — what and why

| Document | Contents |
| --- | --- |
| [product.md](docs/context/product.md) | Problem, personas, scope, differentiators, success metrics, user stories |
| [architecture.md](docs/context/architecture.md) | Topology, tenancy, ACL model, versioning, retrieval pipeline, citations, injection defense, groundedness, evaluation, cost, resilience, data model, ADRs, deployment |
| [roadmap.md](docs/context/roadmap.md) | Eight dependency-ordered phases with exit criteria; deferred list; requirement-coverage matrix |

### Standards — how we build

| Document | Contents |
| --- | --- |
| [conventions.md](docs/standards/conventions.md) | Toolchain, module boundaries, code style, database and migration rules, logging, git, definition of done |
| [api_rules.md](docs/standards/api_rules.md) | Versioning, auth, error format, streaming, rate limits, full v1 endpoint inventory |
| [testing.md](docs/standards/testing.md) | Eight test tiers, coverage targets, the security suite, eval gates, CI pipeline |
| [ai_agent_rules.md](docs/standards/ai_agent_rules.md) | Rules for AI agents in this repo, plus the LLM-integration constraints that are correctness-critical |

### Execution — where we are

| Document | Contents |
| --- | --- |
| [current_task.md](docs/execution/current_task.md) | The one task in progress, and what is next |
| [work_log.md](docs/execution/work_log.md) | Append-only record of completed work and decisions |
| [review_notes.md](docs/execution/review_notes.md) | Review findings register and the standing review checklist |
| [test_evidence.md](docs/execution/test_evidence.md) | What was run, what it showed, and the quality/security snapshot tables |
| [tasks/](docs/tasks/README.md) | Task numbering, lifecycle, and the task spec template |

## Getting started

```bash
cp .env.example .env
uv sync --all-packages --group dev
cd apps/web && npm install && cd ../..
docker compose -f infra/compose/docker-compose.yml up -d postgres redis minio
make migrate && make seed
uv run uvicorn inference.main:app --host 127.0.0.1 --port 8001 &
uv run uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload &
cd apps/web && npm run dev
```

### Dev auth

`.env.example` ships `DEV_AUTH_BYPASS=false`. To use the header-based dev login,
set `DEV_AUTH_BYPASS=true` in your local `.env`, then send `X-Dev-User: acme-member`.

> **`DEV_AUTH_BYPASS=true` trusts that header with no verification — any caller can
> become any user.** Use it only on a development machine. `make up` sets it for the
> local Compose stack; nothing else should.

Seeded roles drive authorization: `acme-admin` (admin — manages ACL entries),
`acme-steward` (curator — uploads and archives documents), `acme-member` and
`acme-viewer` (read-only, and they see different documents by ACL).

### Evals

The harness scores real retrieval against the fixture corpus — it needs Postgres,
a seeded tenant, and the inference service running:

```bash
uv run python -m evals.harness.run --load-corpus   # ingest evals/fixtures, then score
uv run python -m evals.harness.run                 # score against the loaded corpus
```

See [current_task.md](docs/execution/current_task.md).

## Licence

See [LICENSE](LICENSE).
