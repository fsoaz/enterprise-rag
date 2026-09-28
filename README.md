# enterprise-rag

**Enterprise RAG Document Intelligence System** — turn a static document repository into an interactive, cited knowledge layer with permission-aware retrieval.

> **Status: Milestone A in progress** — live status in [current_task.md](docs/execution/current_task.md). Implemented: real OIDC sign-in, real BGE-M3 and BGE-reranker-v2-m3 weights, multi-turn chat, a PT/EN interface, keyset pagination, a tenant-scoped evaluation API with a deterministic CI gate, and a frontend test tier. CI and the integration-test helper select the deterministic inference backend for reproducible checks. Set `ANTHROPIC_API_KEY` for synthesized answers; without one the system abstains rather than guessing.
>
> A security pass and QA remediation rounds closed the defects recorded in [review_notes.md](docs/execution/review_notes.md); see [work_log.md](docs/execution/work_log.md).
>
> **Not yet measured:** answer quality, latency and cost against the live Anthropic API, which needs production credentials. The deterministic stub-backed eval gate runs on pull requests, pushes to `main`, and a nightly full run; the first hosted smoke result is still pending before [R-031](docs/execution/review_notes.md) can close.

---

## What this is

Employees waste hours searching policies, contracts, technical documentation, and internal procedures. Conventional search returns documents; people need answers — with the source attached, so the answer can be trusted and audited.

This system answers questions in Portuguese or English, grounded in an organization's own documents, with a citation on every claim pointing at the exact span in the exact document version it came from. It respects per-document permissions *at retrieval time*, detects when documents are going stale, and refuses to answer when the corpus does not support one.

## Stack

| Layer | Choice |
| --- | --- |
| API | Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) |
| Search | PostgreSQL 16 + pgvector (HNSW) + Postgres FTS (`portuguese` / `english`), fused with RRF |
| Embeddings | BGE-M3, self-hosted — 1024-dim, multilingual |
| Reranking | BGE-reranker-v2-m3, self-hosted cross-encoder |
| Generation | Anthropic Claude — `claude-opus-5` primary, `claude-haiku-4-5` for judging; `claude-sonnet-5` is registered as a fallback but not yet called |
| Jobs / cache | Celery + Redis |
| Storage | MinIO (dev) / S3 (cloud) |
| Frontend | Next.js (App Router) · TypeScript · Tailwind CSS · no component library |
| Auth | OIDC Authorization Code + PKCE — Keycloak (dev); tokens held server-side in `HttpOnly` cookies |
| Deploy | Docker Compose (dev); AWS/Terraform deployment is proposed, not implemented |

No orchestration framework, no managed vector database. Both are deliberate — see [ADR-001](docs/context/architecture.md#adr-001--no-orchestration-framework) and [ADR-002](docs/context/architecture.md#adr-002--postgres-only-search).

## What makes it different from a tutorial

| | |
| --- | --- |
| **Permission-aware retrieval** | ACLs are compiled into the ranking query, not applied afterwards. Post-filtering silently collapses recall and leaks result counts. |
| **Native citations** | Character-level spans returned by the API, not `[1]`/`[2]` markers the model could invent — and the UI links each answer sentence to the span that supports it. |
| **Unsupported-answer detection** | With a live model: citation coverage + an entailment judge + retrieval confidence, the last normalized per strategy so one threshold is meaningful across all four. Without one, the degraded path has no judge and no synthesis, so it abstains unless full-text search finds real evidence — never `grounded`. See [ADR-012](docs/context/architecture.md#adr-012--degraded-mode-evidence-is-lexical-or-it-does-not-exist). |
| **Enforced injection defense** | Multilingual injection patterns are scored at ingest and acted on in SQL on both retrieval arms. Structural chat-template markers are filtered out entirely; linguistic patterns — override, jailbreak, exfiltration — stay retrievable and reach the model labelled `[UNTRUSTED]`, so a security policy that quotes the vocabulary is still answerable. The eval report measures exclusion rate; this is defense in depth, not a claim of universal jailbreak immunity. |
| **Evaluation harness** | Eight-slice bilingual golden set, a tenant-scoped evaluation API, and a deterministic CI regression gate. An evaluation dashboard is not implemented. |
| **Retrieval-strategy comparison** | The harness can compare strategies; results from stub embeddings must not be treated as semantic-quality claims. |
| **Tokens never reach the browser** | The Next.js server runs the OIDC exchange and proxies every API call with the bearer header attached. An XSS in the UI cannot exfiltrate a credential, because there is none in the page. See [ADR-013](docs/context/architecture.md#adr-013--the-browser-never-holds-a-token). |
| **Freshness detection** | Chunks belong to document *versions*. Uploading a replacement through `POST /documents/{id}/versions` supersedes the current version rather than creating a second document, so old citations stay resolvable and each citation carries a computed freshness badge. |

## Architecture at a glance

```text
browser ──▶ Next.js server ──▶ FastAPI api ──┬──▶ Postgres 16 + pgvector + FTS + RLS
   (session cookie)  │  (bearer token)       ├──▶ Redis (cache · queue · limits)
                     │                       ├──▶ S3 / MinIO (original files)
                     ▼                       ├──▶ inference (BGE-M3 · BGE-reranker-v2-m3)
                 Keycloak                    └──▶ Anthropic API
                  (OIDC)                              ▲
                             Celery worker ───────────┘  (ingest · reindex · freshness)
```

Full diagram and component contracts: [architecture.md § 3](docs/context/architecture.md#3-component-topology).

## Getting started

### Prerequisites

- Python **3.12** (`>=3.12,<3.13`), GNU Make, and Bash.
- uv with `uv run --env-file` support. [VERIFY] No minimum version is pinned for
  host use; the container images use uv 0.6.14.
- Docker Engine and Docker Compose **v2.24.0 or later** (the Compose file uses
  optional `env_file` entries).
- Node **22** and npm for local frontend development and contribution checks.
- curl for readiness checks; network access for dependencies, images, and model weights.
- Free host ports 3000, 8000, 8001, 8080, 15432, 16379, 19000, and 19001
  ([port reference](docs/guides/local-development.md#ports)).

Postgres 16 with pgvector, Redis, MinIO, and Keycloak run in Compose. Real BGE
models run on CPU by default. First startup includes image builds and model
loading and may take more than ten minutes; no fixed RAM/disk minimum has been
measured for this project. Check available resources if model loading fails.

### Install, configure, and run

Run from the repository root. On a fresh checkout:

```bash
cp .env.example .env
uv sync --all-packages --group dev
```

Keep an existing `.env` instead of overwriting it. Review [.env.example](.env.example)
for configuration. Leave the Anthropic key placeholder unchanged to use degraded
responses, or set your own `ANTHROPIC_API_KEY` for synthesized answers.

Start the full development stack:

```bash
make up
```

This builds and starts the services, applies migrations, seeds demo identities
and collections, and starts the API, worker, inference, and web. The seed does
not load document content. Compose configures the web container directly;
`apps/web/.env.local` is used only when running the frontend locally.

For hot reload or Python service development, follow
[Run processes separately](docs/guides/local-development.md#run-processes-separately),
which includes environment loading and worker startup.

### Verify that it works

```bash
curl --fail --silent --show-error http://localhost:8001/ready
curl --fail --silent --show-error http://localhost:8000/health
curl --fail --silent --show-error http://localhost:8000/ready
```

Expect inference readiness, API liveness, and API readiness respectively; HTTP 503
from API readiness means a database, Redis, or inference check failed. The
[startup checks](docs/guides/local-development.md#verify-startup) also cover
Keycloak and the web server.

Open `http://localhost:3000`, choose **Sign in**, and use `acme-steward` /
`acme-steward`. Every seeded identity's password equals its username; the
[identity table](docs/guides/local-development.md#development-sign-in) lists the
Acme and Globex users, their roles, and what they can see. Access and refresh
tokens remain in HttpOnly cookies; the Next.js server refreshes and forwards them
to FastAPI. Then [verify a first upload](docs/guides/local-development.md#verify-an-upload).
For failures, use the [troubleshooting guide](docs/guides/local-development.md#troubleshooting).

Stop the stack with `make down`; Compose data volumes are retained.

### Network exposure

Header-based impersonation (`DEV_AUTH_BYPASS=true`) lets any caller become any
user in any tenant; Compose forces it off, and the
[local-development guide](docs/guides/local-development.md#header-based-impersonation-bypass)
explains the development-only setup.

The Compose stack uses development credentials throughout (default
Postgres/MinIO/Keycloak passwords and no Redis auth), so **every published port
binds to `127.0.0.1` by default**. Overriding that exposes the development
identity provider and data services to anything that can route to the host:

```bash
BIND_ADDR=0.0.0.0 make up   # only on an isolated network you control
```

### Rate limits and budget

Per-user request caps and a rolling 24-hour spend ceiling are enforced by default —
see `RATE_LIMIT_*` and `TENANT_DAILY_BUDGET_USD` in `.env.example`. Rate limiting
fails **open** when Redis is unreachable (a cache outage should not be a full
outage); the budget guard reads `cost_ledger` in Postgres, so it holds regardless.

## Documentation

Developer guides, architecture notes, ADRs, and the review register are tracked in
`docs/` and maintained with the implementation. Start with the
[local development and troubleshooting guide](docs/guides/local-development.md).
The [generated OpenAPI schema](openapi.json) is the current API reference; a running
API also serves interactive documentation at `http://localhost:8000/api/docs`.

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
| [api_rules.md](docs/standards/api_rules.md) | API guidance, upload/job workflow, and planned interfaces; use OpenAPI for current routes |
| [testing.md](docs/standards/testing.md) | Test tiers, coverage targets, security checks, and implemented versus proposed CI gates |
| [ai_agent_rules.md](docs/standards/ai_agent_rules.md) | Rules for AI agents in this repo, plus the LLM-integration constraints that are correctness-critical |

### Execution — where we are

| Document | Contents |
| --- | --- |
| [current_task.md](docs/execution/current_task.md) | The one task in progress, and what is next |
| [work_log.md](docs/execution/work_log.md) | Append-only record of completed work and decisions |
| [review_notes.md](docs/execution/review_notes.md) | Review findings register and the standing review checklist |
| [test_evidence.md](docs/execution/test_evidence.md) | What was run, what it showed, and the quality/security snapshot tables |
| [qa_report_2026-07-26.md](docs/execution/qa_report_2026-07-26.md) | Full QA review of Milestone A — 37 findings and their disposition |
| [qa_report_2026-07-29.md](docs/execution/qa_report_2026-07-29.md) · [qa_report_2026-07-31.md](docs/execution/qa_report_2026-07-31.md) | Follow-up QA reviews |
| [tasks/](docs/tasks/README.md) | Task numbering, lifecycle, and the task spec template |

## Contributing

Read [engineering conventions](docs/standards/conventions.md) and
[testing standards](docs/standards/testing.md). Use Conventional Commits, link the
relevant [task](docs/tasks/README.md), and include verification evidence in the PR.
Update documentation alongside behavior changes. For API changes, follow the
[canonical generation workflow](docs/standards/conventions.md#2-toolchain).
Install frontend dependencies with `npm ci --prefix apps/web` before running checks.

### Tests

```bash
make lint typecheck        # ruff · biome · mypy · import-linter · tsc
make test                  # pytest, unit tier
make test-integration      # creates, migrates, seeds, tests, and drops a disposable database
make migrate-check         # runs the migration chain from an EMPTY database, as CI does
npm run test:coverage --prefix apps/web  # vitest with the CI coverage thresholds
```

`make test-integration` will not touch the development database: the target name must end
in `_test` or start with `test_`, and the helpers refuse anything else. Use `make
migrate-check` before committing a migration — `make migrate` only moves your existing
database forward, so it cannot see a conflict with a from-scratch build.

### Evals

The harness scores real retrieval against the fixture corpus — it needs Postgres,
a seeded tenant, and the inference service running:

```bash
uv run --no-sync --env-file .env python -m evals.harness.run --load-corpus   # ingest evals/fixtures, then score
uv run --no-sync --env-file .env python -m evals.harness.run                 # score against the loaded corpus
```

Scores are only meaningful on a corpus you rebuilt with `--load-corpus`.
`INFERENCE_BACKEND=stub` is only a deterministic wiring profile and its scores must not be
published as semantic quality. Compose and the documented local command default to
`INFERENCE_BACKEND=bge`; startup fails rather than silently falling back if the model extra
or weights are unavailable. Current figures and their caveats:
[test_evidence.md](docs/execution/test_evidence.md).

## Configuration

[.env.example](.env.example) documents the supported environment variables. LLM
model identities are selected in `packages/llm/src/llm/models.py`, not through the
environment; evaluation runs record their requested generator identity. Server
binding comes from the `uvicorn --host ... --port ...` startup command (the API
image uses `0.0.0.0:8000`). Embedding and inference model selection, and which
settings reach each Compose service, are described in
[configuration loading](docs/guides/local-development.md#configuration-loading).

## Licence

See [LICENSE](LICENSE).
