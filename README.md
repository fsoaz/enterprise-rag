# enterprise-rag

**Enterprise RAG Document Intelligence System** — turn a static document repository into an interactive, cited knowledge layer with permission-aware retrieval.

> **Status: Milestone A complete, after a security pass and a full QA remediation round.** Real OIDC sign-in, real BGE-M3 and BGE-reranker-v2-m3 weights, multi-turn chat, a PT/EN interface, keyset pagination, and a frontend test tier. CI alone selects the deterministic inference backend, so tests stay offline and reproducible. Set `ANTHROPIC_API_KEY` for synthesized answers; without one the system abstains rather than guessing.
>
> Those rounds closed the defects in [review_notes.md](docs/execution/review_notes.md) — an abstention gate structurally stuck on under the default strategy, ingest failures that were never recorded, a prompt-injection score nothing read, and a frontend with no configuration that was both functional and safe. See [work_log.md](docs/execution/work_log.md).
>
> **Not yet measured:** answer quality, latency and cost against the live Anthropic API, which needs production credentials. The eval harness is still a local command rather than a CI gate ([R-031](docs/execution/review_notes.md)).

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
| Frontend | Next.js (App Router) · TypeScript · Tailwind CSS · no component library |
| Auth | OIDC Authorization Code + PKCE — Keycloak (dev); tokens held server-side in `HttpOnly` cookies |
| Deploy | Docker Compose (dev) · Terraform → AWS ECS Fargate (cloud) |

No orchestration framework, no managed vector database. Both are deliberate — see [ADR-001](docs/context/architecture.md#adr-001--no-orchestration-framework) and [ADR-002](docs/context/architecture.md#adr-002--postgres-only-search).

## What makes it different from a tutorial

| | |
| --- | --- |
| **Permission-aware retrieval** | ACLs are compiled into the ranking query, not applied afterwards. Post-filtering silently collapses recall and leaks result counts. |
| **Native citations** | Character-level spans returned by the API, not `[1]`/`[2]` markers the model could invent — and the UI links each answer sentence to the span that supports it. |
| **Unsupported-answer detection** | With a live model: citation coverage + an entailment judge + retrieval confidence, the last normalized per strategy so one threshold is meaningful across all four. Without one, the degraded path has no judge and no synthesis, so it abstains unless full-text search finds real evidence — never `grounded`. See [ADR-012](docs/context/architecture.md#adr-012--degraded-mode-evidence-is-lexical-or-it-does-not-exist). |
| **Enforced injection defense** | Multilingual structural injection patterns are scored at ingest and filtered in SQL on both retrieval arms; borderline chunks reach the model labelled `[UNTRUSTED]`. The eval report measures exclusion rate; this is defense in depth, not a claim of universal jailbreak immunity. |
| **Evaluation harness** | Eight-slice bilingual golden set for local, reproducible measurement. CI/eval dashboard integration is not implemented. |
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
| [qa_report_2026-07-26.md](docs/execution/qa_report_2026-07-26.md) | Full QA review of Milestone A — 37 findings and their disposition |
| [tasks/](docs/tasks/README.md) | Task numbering, lifecycle, and the task spec template |

## Getting started

```bash
cp .env.example .env
cp apps/web/.env.example apps/web/.env.local
uv sync --all-packages --group dev
uv sync --package enterprise-rag-inference --extra models  # real BGE runtime
cd apps/web && npm install && cd ../..
docker compose -f infra/compose/docker-compose.yml up -d postgres redis minio keycloak
make migrate && make seed
uv run uvicorn inference.main:app --host 127.0.0.1 --port 8001 &
uv run uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload &
cd apps/web && npm run dev
```

### Dev auth and network exposure

The default path is real OIDC Authorization Code + PKCE against the imported
`enterprise-rag` Keycloak realm. Open `http://localhost:3000`, choose **Sign in**,
and use a seeded identity such as `acme-member` / `acme-member` or
`acme-steward` / `acme-steward`. Access and refresh tokens remain in HttpOnly
cookies; the Next.js server refreshes and forwards them to FastAPI.

The realm and database seed share stable tenant UUIDs. If the database predates
this auth setup, run `make db-reset` once so its seeded identities match the realm.

To use header-based impersonation instead, set `DEV_AUTH_BYPASS=true` in `.env`
and `NEXT_PUBLIC_DEV_AUTH=true` in `apps/web/.env.local`, then restart both API
and web. The browser sends `X-Dev-User` only in that explicit mode.

> **`DEV_AUTH_BYPASS=true` trusts that header with no verification — any caller can
> become any user, in any tenant.** Use it only on a development machine.

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

Seeded roles drive authorization: `acme-admin` (admin — manages ACL entries),
`acme-steward` (curator — uploads and archives documents), `acme-member` and
`acme-viewer` (read-only, and they see different documents by ACL).

### Tests

```bash
make lint typecheck        # ruff · biome · mypy · import-linter · tsc
make test                  # pytest, unit tier
make test-integration      # creates, migrates, seeds, tests, and drops a disposable database
make migrate-check         # runs the migration chain from an EMPTY database, as CI does
cd apps/web && npm test    # vitest — components and browser-side modules
```

`make test-integration` will not touch the development database: the target name must end
in `_test` or start with `test_`, and the helpers refuse anything else. Use `make
migrate-check` before committing a migration — `make migrate` only moves your existing
database forward, so it cannot see a conflict with a from-scratch build.

### Evals

The harness scores real retrieval against the fixture corpus — it needs Postgres,
a seeded tenant, and the inference service running:

```bash
uv run python -m evals.harness.run --load-corpus   # ingest evals/fixtures, then score
uv run python -m evals.harness.run                 # score against the loaded corpus
```

Scores are only meaningful on a corpus you rebuilt with `--load-corpus`.
`INFERENCE_BACKEND=stub` is only a deterministic wiring profile and its scores must not be
published as semantic quality. Compose and the documented local command default to
`INFERENCE_BACKEND=bge`; startup fails rather than silently falling back if the model extra
or weights are unavailable. Current figures and their caveats:
[test_evidence.md](docs/execution/test_evidence.md).

See [current_task.md](docs/execution/current_task.md).

## Licence

See [LICENSE](LICENSE).
