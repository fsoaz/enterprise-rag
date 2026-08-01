# Engineering Conventions

> **Applies to:** every contributor, human or AI.
> **Related:** [api_rules.md](./api_rules.md) · [testing.md](./testing.md) · [ai_agent_rules.md](./ai_agent_rules.md) · [../context/architecture.md](../context/architecture.md)

Rules here are enforced by tooling wherever possible. A rule that cannot be enforced by a linter, a type checker, or a test is a rule that will be forgotten.

---

## 1. Languages & Runtimes

| Component | Runtime | Pinned by |
| --- | --- | --- |
| `api`, `worker`, `inference`, `packages/*` | Python 3.12 | `.python-version`, `pyproject.toml` |
| `web` | Node 22 LTS, TypeScript 5.x | `.nvmrc`, `package.json` |
| Database | PostgreSQL 16 + pgvector ≥ 0.7 | Compose image tag, Terraform |

No compatibility shims for older runtimes. If a dependency requires an older Python, replace the dependency.

## 2. Toolchain

| Concern | Tool | Config |
| --- | --- | --- |
| Python packaging & deps | `uv` | `pyproject.toml`, `uv.lock` committed |
| Python lint + format | `ruff` (both) | `ruff.toml` |
| Python types | `mypy` | `--strict` on `packages/`, standard on `apps/` |
| Python import boundaries | `import-linter` | `.importlinter` |
| TS lint + format | `biome` | `biome.json` |
| TS types | `tsc --noEmit` | `tsconfig.json`, `strict: true` |
| Migrations | Alembic | `packages/db/migrations/` |
| Python tests | `pytest` | see [testing.md](./testing.md) |
| Frontend tests | `vitest` + Testing Library + jsdom | `apps/web/vitest.config.ts` |
| Generated API types | `openapi-typescript` | `npm run generate:api-types` → `src/lib/generated/api.ts` |
| Hooks | `pre-commit` | format, lint, secret scan, migration check |

`black`, `isort`, `flake8`, `eslint`, and `prettier` are **not** used — `ruff` and `biome` replace them. Do not add them back. `jest` is likewise not used; `vitest` is the frontend runner.

**`src/lib/generated/` is output, not source.** Edit `openapi.json` upstream and regenerate; CI runs the generator and fails on any diff, so a hand-edit is reverted by the next run rather than surviving as an untracked local behavior.

After an OpenAPI change, regenerate the frontend types using the lockfile-pinned toolchain, then commit the output:

```bash
cd apps/web
npm ci
npm run generate:api-types
git diff --exit-code src/lib/generated/api.ts
```

Use `npm ci`, not `npm install`: CI resolves `openapi-typescript` from `package-lock.json`, and a different generator version can produce a spurious generated-file diff. Commit `src/lib/generated/api.ts` when the command changes it.

## 3. Repository Layout

Canonical layout is in [architecture.md § 16](../context/architecture.md#16-repository-layout). Two rules that matter more than the rest:

1. **`apps/` are deployables. `packages/` are libraries.** If two apps need the same logic, it moves to `packages/`. It is never imported across app boundaries.
2. **A new top-level directory needs a note in the task file explaining why.** The layout is a decision, not a default.

## 4. Module Boundaries

Enforced by `import-linter` in CI. The contract:

```text
packages/domain      → imports nothing from this project
packages/db          → may import domain
packages/retrieval   → may import domain, db
packages/llm         → may import domain
packages/observability → may import nothing from this project

apps/api             → may import any package
apps/worker          → may import any package
apps/inference       → may import observability only
apps/web             → HTTP only; no Python imports
```

**Forbidden, and the build fails on them:**

- `packages/*` importing from `apps/*`
- `apps/api` importing `apps/worker` internals, or the reverse
- `packages/domain` importing SQLAlchemy, FastAPI, or the Anthropic SDK — the domain layer has no I/O and no framework

## 5. Python Style

### 5.1 Baseline

- `ruff format` output is the only acceptable formatting. No manual alignment.
- Line length 100.
- Full type hints on every function signature, including `-> None`.
- `from __future__ import annotations` at the top of every module.

### 5.2 Rules with teeth

| Rule | Why |
| --- | --- |
| **No bare `except:` and no bare `except Exception:`** without a re-raise or a logged, typed handler | Swallowed exceptions in an ingestion pipeline mean silently missing documents |
| **Async-first in `api`** — no blocking I/O in a request path | One blocking call stalls the whole event loop |
| **No mutable default arguments** | Classic footgun; `ruff` catches it |
| **Prefer composition over inheritance**; service classes take dependencies via constructor | Makes testing possible without patching |
| **`Protocol` for interfaces**, not ABCs, unless shared implementation is genuinely needed | Structural typing keeps `packages/domain` free of framework coupling |
| **No module-level side effects** — no I/O, no client construction, no `os.environ` reads at import time | Import-time side effects break testing and cold starts |
| **`datetime.now(tz=UTC)`**, never naive datetimes | Timezone bugs in `effective_from` / `effective_to` are correctness bugs, not cosmetic |
| **`Decimal` for money**, never `float` | The cost ledger must add up |

### 5.3 Naming

| Kind | Convention | Example |
| --- | --- | --- |
| Modules, functions, variables | `snake_case` | `resolve_acl_predicate` |
| Classes | `PascalCase` | `HybridRetriever` |
| Constants | `SCREAMING_SNAKE` | `DEFAULT_RRF_K` |
| Private | leading underscore | `_build_cte` |
| Booleans | predicate form | `is_current`, `has_citations`, `should_abstain` |
| Async functions | no `async_` prefix | `fetch_chunks`, not `async_fetch_chunks` |

### 5.4 Errors

Domain code raises **typed domain exceptions** from `packages/domain/errors.py`. Only the HTTP boundary translates them to responses.

```text
DomainError
├── NotFoundError
├── PermissionDeniedError
├── ValidationError
├── ConflictError
├── QuotaExceededError
└── DependencyError
    ├── RetrievalUnavailable
    ├── InferenceUnavailable
    └── GenerationUnavailable
```

A FastAPI exception handler maps each to an RFC 7807 response per [api_rules.md § 5](./api_rules.md#5-errors). Domain code never imports `HTTPException`.

## 6. TypeScript & Frontend Style

- `strict: true`. No `any`. `unknown` plus a narrowing guard where a type is genuinely open.
- Server Components by default; `"use client"` only where interactivity requires it.
- Data fetching in server components or route handlers, never `useEffect` fetch waterfalls.
- Types for API payloads are **generated from the committed OpenAPI schema**, not hand-written. A drift between them is a CI failure.
- Components: one per file, `PascalCase` filename matching the export.
- Styling: Tailwind utility classes, no ad-hoc CSS files. **There is no component library** — every control is hand-rolled. shadcn/ui was named in early drafts and never adopted; do not cite it as present.
- Every interactive element is keyboard-reachable and has an accessible name.
- Both light and dark themes are supported — `prefers-color-scheme` plus an explicit toggle.

### 6.1 User-facing strings

- **No user-facing string is written inline in a component.** Every one goes through `t()` from `src/lib/i18n.tsx`, in both `en` and `pt`.
- The dictionaries are typed `Record<Locale, Record<MessageKey, string>>`, so a key added to one locale and not the other is a `tsc` failure. That is the enforcement mechanism — there is no runtime fallback to the key name and none should be added, because a silent fallback turns a build error into a string the user sees.
- This covers error and fallback text too. A backend `problem+json` `detail` is English, so the UI maps known error slugs to translated messages and uses the raw detail only when it has no mapping.
- `lang` on `<html>` follows the active locale, and the answer paragraph carries its own `lang` when the answer language differs from the UI language.

### 6.2 Server/client boundary for secrets

- Anything holding a token, a client secret, or a cookie is `import "server-only"` at the top of the file. That import is what makes a mistaken client import a build failure rather than a bundled secret.
- `NEXT_PUBLIC_*` is a publication decision, not a naming convention: the value ends up in the JavaScript the browser downloads. Nothing sensitive gets that prefix.
- Browser code never calls the FastAPI origin directly in the authenticated configuration — it calls `/api/backend/...` and the server attaches the bearer token ([ADR-013](../context/architecture.md#adr-013--the-browser-never-holds-a-token)).

## 7. Database Conventions

| Rule | Detail |
| --- | --- |
| Table names | plural, `snake_case` — `document_versions` |
| Primary keys | `id uuid PRIMARY KEY DEFAULT gen_random_uuid()` |
| Foreign keys | `<singular>_id`, always with an explicit `ON DELETE` action |
| Timestamps | `created_at`, `updated_at`, both `timestamptz NOT NULL DEFAULT now()` |
| Soft delete | Not used. Use status columns or the version chain. |
| Tenant column | **Every tenant-scoped table has `tenant_id uuid NOT NULL`** — no exceptions, checked by a test |
| RLS | Enabled on every tenant-scoped table, with a policy on `current_setting('app.current_tenant')` |
| Enums | Postgres native enums for closed sets that rarely change; `text` + `CHECK` where values evolve |
| JSON | `jsonb`, never `json`; only for genuinely schemaless data (`settings`, `metrics`, `params`) |
| Indexes | Named `ix_<table>__<cols>`; every foreign key used in a filter gets one |
| Pagination | Keyset on `(created_at DESC, id DESC)`, never `OFFSET`. A paginated endpoint ships with a composite index whose columns **and directions** match its `ORDER BY` exactly — a mismatched direction still answers the query but cannot be walked as a seek, so the plan silently degrades to sorting the whole partition ([ADR-014](../context/architecture.md#adr-014--pagination-cursors-encode-a-position-not-an-offset)) |

### 7.1 Migrations

- One Alembic revision per PR. Two revisions in one PR means the PR is doing two things.
- **Every migration is reversible.** `downgrade()` is written and exercised in CI.
- **A merged migration is immutable.** Fix forward with a new revision; never edit history.
- **Test migrations from an empty database, not from your dev database's revision.** `make migrate-check` builds a throwaway database, runs `upgrade head → downgrade -1 → upgrade head`, and seeds it. `make migrate` only moves your dev database forward from wherever it already is, so it cannot catch a migration that conflicts with a from-scratch build.
- **`0001_initial` is not immutable in practice.** It builds the schema with `Base.metadata.create_all()`, so it re-derives from *current* model metadata on every run. Adding an `Index` to a model's `__table_args__` therefore changes what an already-released migration creates, and a fresh database ends up with objects an existing one lacks. Until 0001 is rewritten as explicit DDL, guard model-derived DDL in later migrations with `IF NOT EXISTS`. This caused a CI failure (R-058).
- **Expand/contract for anything breaking.** Add the new column → deploy code that writes both → backfill → deploy code that reads the new → drop the old. No deploy may require a simultaneous schema and code cutover.
- Data migrations that touch many rows are batched and idempotent.
- Adding a tenant-scoped table without RLS fails the migration test.

## 8. Configuration & Secrets

- 12-factor: all configuration comes from environment variables, read through a single `pydantic-settings` object per app. No `os.environ` scattered through the codebase.
- `.env.example` lists every variable with a comment and a safe placeholder. Adding a variable without updating it fails CI.
- **No secret is ever committed.** `gitleaks` runs in pre-commit and in CI.
- Local secrets live in `.env` (gitignored). Cloud secrets live in AWS Secrets Manager, injected at task start.
- Secrets are never logged, never included in error messages, and never returned by an API endpoint.

## 9. Logging

- `structlog`, JSON output, one event per line.
- Every line carries `request_id`, `tenant_id`, `user_id` (when authenticated), and `route` or `task`.
- Levels: `debug` (local only), `info` (state transitions), `warning` (degraded but served), `error` (request failed), `critical` (dependency down).

**Never logged, under any level:**

- Document content, chunk text, or answer text
- The user's question at `info` or above (hash it, or log at `debug` in local only)
- Tokens, API keys, JWTs, or any credential
- Full email addresses (log the user ID)

A test in the security suite asserts these do not appear in captured log output.

## 10. Git

### 10.1 Branching

Trunk-based. `main` is always deployable. Feature branches are short-lived and named `<type>/<task-id>-<slug>` — e.g. `feat/T-205-rrf-fusion`.

No direct pushes to `main`. Branch protection requires a green CI run and one review.

### 10.2 Commits

Conventional Commits. Subject ≤ 50 characters, imperative mood, no trailing period.

```text
feat(retrieval): fuse dense and lexical arms with RRF

Single SQL statement with both arms as CTEs so fusion costs one
round trip instead of two. k=60 per the literature default; exposed
as a tunable for the strategy comparison.
```

Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `chore`, `build`, `ci`.
Scopes: `api`, `worker`, `inference`, `web`, `db`, `retrieval`, `llm`, `evals`, `infra`, `docs`.

Body only when the *why* is not obvious from the subject. Explain the reasoning, not the diff — the diff is already in the commit.

### 10.3 Pull requests

Template requires:

- Link to the task file in `docs/tasks/`
- What changed and why
- How it was verified (commands run, evidence)
- Migration notes, if any
- Screenshots for UI changes

One task per PR. A PR that touches three unrelated areas gets split.

## 11. Dependencies

- A new dependency requires a note in the task file: what it does, why the standard library or an existing dependency is insufficient, and its maintenance status.
- Prefer the standard library. Prefer a well-maintained small library over a framework.
- Lockfiles (`uv.lock`, `package-lock.json`) are committed and updated deliberately, never regenerated as a side effect.
- `pip-audit` and `npm audit` run in CI. High-severity advisories block the merge.
- **The gate is on the production tree.** `npm audit --omit=dev` is what blocks; the full audit currently reports four high-severity advisories reachable only through the `openapi-typescript` generation chain, which runs on a developer machine and in CI and ships in nothing. Forcing overrides there breaks the generator. A dev-only advisory is recorded and reviewed, not force-resolved into a broken toolchain — but "dev-only" is a claim that has to be checked against the dependency path each time, not assumed from the section of `package.json` it appears in.

## 12. Documentation

- **`docs/` is tracked in git and must stay that way.** It was ignored until 2026-08-01, which broke all 23 README links on a fresh clone and kept the ADRs, the review register, and the QA reports off the record the code ships with (R-099). Documentation that only exists on one machine cannot be the source of truth for anything.
- **`docs/context/` is the source of truth for design.** Code that contradicts it means one of the two is wrong; resolve before merging.
- Every architectural decision that closes an open question becomes an ADR in [architecture.md § 15](../context/architecture.md#15-architecture-decision-records).
- Docstrings on public functions in `packages/`: what it does, what it raises, non-obvious constraints. Not a restatement of the signature.
- Comments explain **why**, never **what**. A comment saying what the next line does is noise; delete it.
- `docs/execution/work_log.md` gets an entry when a task completes.

## 13. Definition of Done

A change is done when all of these hold. Not before.

- [ ] Acceptance criteria in the task file are met
- [ ] Lint, format, and type checks pass
- [ ] Unit tests cover the new logic; integration tests cover the new I/O
- [ ] Frontend changes have a Vitest test that exercises the path the user takes — `tsc`, `biome` and `next build` do not load a page and cannot observe behavior
- [ ] Security tests still pass — tenant isolation and ACL specifically
- [ ] Eval smoke subset shows no regression beyond threshold
- [ ] Migration is reversible and exercised
- [ ] `.env.example` and OpenAPI schema updated if the surface changed
- [ ] No secret, no document content, and no PII in logs
- [ ] Docs updated if behavior or design changed
- [ ] [work_log.md](../execution/work_log.md) entry appended
- [ ] Verification evidence recorded in [test_evidence.md](../execution/test_evidence.md)
