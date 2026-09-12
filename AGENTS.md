# Repository Guidelines

## Project Structure & Module Organization

`apps/` contains deployables: FastAPI `api`, Celery `worker`, model-serving `inference`, and Next.js `web`. Python code lives in each component’s `src/`; shared libraries live in `packages/{domain,db,retrieval,llm,observability}`. Libraries must not import apps; apps must not import each other’s internals.

Python tests live in component `tests/` directories and root `tests/`. Frontend tests sit beside source files; static assets live in `apps/web/public/`. `evals/` holds synthetic fixtures, datasets, and the evaluation harness. Alembic revisions live in `packages/db/migrations/`; local infrastructure lives in `infra/compose/`. Consult `docs/context/` and `docs/standards/` for design and engineering rules.

## Build, Test, and Development Commands

Use Python 3.12, Node 22, and `uv`. Run these from the repository root:

- `uv sync --all-packages --group dev`: install Python dependencies.
- `npm ci --prefix apps/web`: install locked frontend dependencies.
- `make up` / `make down`: start or stop the Compose stack; startup migrates and seeds Postgres.
- `npm run dev --prefix apps/web`: run the frontend locally.
- `npm run build --prefix apps/web`: build the production frontend.
- `make lint typecheck`: check Ruff, Biome, mypy, import boundaries, and TypeScript.
- `make format`: apply Python and TypeScript formatting.
- `make test`: run non-integration pytest tests.
- `make test-integration`: test against a disposable database.
- `make migrate-check`: validate migration upgrade/downgrade against an empty database.
- `npm run test:coverage --prefix apps/web`: run frontend tests with coverage.

## Coding Style & Naming Conventions

Use four-space Python indentation, full type hints, `snake_case` functions, and `PascalCase` classes. Ruff enforces 100-character lines. TypeScript uses strict typing, Biome, two-space indentation, double quotes, and `PascalCase` component filenames. Route UI strings through `t()` with English and Portuguese translations.

## Testing Guidelines

Use pytest/pytest-asyncio and Vitest/Testing Library. Name Python tests `test_<unit>__<condition>__<expected>`; frontend files use `.test.ts` or `.test.tsx`. Keep unit tests offline; cover tenant isolation and denied access. Frontend coverage minimums are 60% statements/lines and 50% branches/functions. Python coverage targets are documented in `docs/standards/testing.md`.

## Commit & Pull Request Guidelines

Follow Conventional Commits, as in `feat: ...` or `chore(web): ...`. Keep PRs focused on one task; link its `docs/tasks/` file and include rationale, verification evidence, migration notes, and UI screenshots when relevant.

## Execution Rules

- Track recorded elapsed time and estimated remaining effort against any explicit task budget and the 15-hour project cap. Mark missing prior usage as unknown; never invent it or assume it is zero. If either limit is likely to be exceeded, stop and report progress, remaining work, and estimated overrun, stating any uncertainty.
- Choose the simplest implementation that meets the acceptance criteria. Keep changes focused and proportional; do not build for hypothetical future requirements.
- Reuse existing code where appropriate. Add abstractions, layers, frameworks, dependencies, configuration, or extension points only when required by the task or an applicable architectural decision.
- Refactor only as needed to complete the task. Record unrelated improvement opportunities in review notes instead of implementing them.
- Explain which requirement each architectural change or new dependency addresses. Follow applicable approval requirements before making the change.
- Preserve existing behavior unless the task requires a change. Add or update tests to verify required behavior changes.
- Preserve unrelated working-tree changes. Limit the task’s diff to requested changes and necessary supporting updates.

## Security & Configuration

Never commit secrets; document configuration in `.env.example`. Preserve tenant scoping and ACL enforcement. After API changes, run `make openapi openapi-check` and `npm run generate:api-types --prefix apps/web`; commit generated outputs without hand-editing them.
