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

## Security & Configuration

Never commit secrets; document configuration in `.env.example`. Preserve tenant scoping and ACL enforcement. After API changes, run `make openapi openapi-check` and `npm run generate:api-types --prefix apps/web`; commit generated outputs without hand-editing them.
