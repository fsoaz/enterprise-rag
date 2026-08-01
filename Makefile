.PHONY: lint typecheck test test-integration format install web-lint web-typecheck up down migrate migrate-check seed db-reset openapi openapi-check

# Throwaway database for migrate-check. Never the dev database.
MIGRATE_CHECK_DB ?= rag_migrate_check
# Compose's project directory is infra/compose/, so root .env is invisible for
# ${VAR} interpolation (publish ports) unless we pass it explicitly. Auth bypass
# is hardcoded false in compose and is not taken from this file.
COMPOSE = docker compose --env-file $(CURDIR)/.env -f infra/compose/docker-compose.yml
PSQL = $(COMPOSE) exec -T -e PGPASSWORD=postgres postgres psql -U postgres

install:
	uv sync --all-packages --group dev
	cd apps/web && npm install

lint:
	uv run ruff check .
	uv run ruff format --check .
	cd apps/web && npx biome check .

format:
	uv run ruff format .
	uv run ruff check --fix .
	cd apps/web && npx biome check --write .

typecheck:
	uv run mypy
	uv run lint-imports
	cd apps/web && npx tsc --noEmit

test:
	uv run pytest -q

# Creates, migrates, seeds, tests, and drops an isolated database. The script
# validates the target name before either destructive database operation.
test-integration:
	bash scripts/run-integration-tests.sh

up:
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example — edit secrets as needed."; fi
	$(COMPOSE) up -d --build postgres redis minio minio-init keycloak
	@echo "Waiting for Postgres..."
	@until $(COMPOSE) exec -T postgres pg_isready -U postgres -d enterprise_rag >/dev/null 2>&1; do sleep 1; done
	$(MAKE) migrate
	$(MAKE) seed
	$(COMPOSE) up -d --build api worker inference web

down:
	@if [ ! -f .env ]; then cp .env.example .env; fi
	$(COMPOSE) down

migrate:
	set -a && [ -f .env ] && . ./.env; set +a; \
	uv run alembic -c packages/db/alembic.ini upgrade head

seed:
	set -a && [ -f .env ] && . ./.env; set +a; \
	uv run python -m db.seed

# Run the migration chain from an EMPTY database, the way CI does.
#
# `make migrate` only ever moves the dev database forward from wherever it already is,
# so it cannot catch a migration that conflicts with a from-scratch build — which is
# exactly how a duplicate-index failure reached CI. 0001_initial uses
# `Base.metadata.create_all()`, so any model-level index it now creates must not be
# re-created by a later migration.
migrate-check:
	@echo ">> creating throwaway database $(MIGRATE_CHECK_DB)"
	@$(PSQL) -q -c "DROP DATABASE IF EXISTS $(MIGRATE_CHECK_DB);" -c "CREATE DATABASE $(MIGRATE_CHECK_DB);"
	@$(PSQL) -q -d $(MIGRATE_CHECK_DB) -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pgcrypto; GRANT USAGE, CREATE ON SCHEMA public TO rag_migrate; GRANT USAGE ON SCHEMA public TO rag_app, rag_maint;"
	@set -e; \
	export DATABASE_URL_MIGRATE="postgresql+psycopg://rag_migrate:rag_migrate@localhost:$${POSTGRES_PUBLISH_PORT:-15432}/$(MIGRATE_CHECK_DB)"; \
	export DATABASE_URL="postgresql+asyncpg://rag_app:rag_app@localhost:$${POSTGRES_PUBLISH_PORT:-15432}/$(MIGRATE_CHECK_DB)"; \
	echo ">> upgrade head (from empty)"; uv run alembic -c packages/db/alembic.ini upgrade head >/dev/null; \
	echo ">> downgrade -1";             uv run alembic -c packages/db/alembic.ini downgrade -1 >/dev/null; \
	echo ">> upgrade head";             uv run alembic -c packages/db/alembic.ini upgrade head >/dev/null; \
	echo ">> seed";                     uv run python -m db.seed >/dev/null; \
	echo ">> OK — migrations apply cleanly from empty"
	@$(PSQL) -q -c "DROP DATABASE IF EXISTS $(MIGRATE_CHECK_DB);"
	@echo ">> throwaway database dropped"

# Drop and rebuild the dev database, then re-seed.
#
# Integration tests write into whatever database DATABASE_URL points at and leave
# rows behind — documents, collections, and ACL grants that are not in db/seed.py.
# Leftover ACL rows silently falsify manual authorization testing in both
# directions, and leftover documents make every retrieval number a measurement of
# the residue rather than of the fixture corpus. Run this before quoting either.
db-reset:
	@echo ">> dropping and recreating enterprise_rag"
	@$(PSQL) -q -c "DROP DATABASE IF EXISTS enterprise_rag WITH (FORCE);" -c "CREATE DATABASE enterprise_rag;"
	@$(PSQL) -q -d enterprise_rag -f /docker-entrypoint-initdb.d/01-init.sql
	$(MAKE) migrate
	$(MAKE) seed
	@echo ">> dev database reset. Reload eval fixtures with:"
	@echo "   uv run python -m evals.harness.run --load-corpus"

# Regenerate the committed OpenAPI documents from the live app.
openapi:
	@uv run python -c "import json, pathlib; from api.main import app; \
	doc = json.dumps(app.openapi(), indent=2, ensure_ascii=False) + '\n'; \
	[pathlib.Path(p).write_text(doc) for p in ('openapi.json', 'apps/web/openapi.json')]"
	@echo ">> openapi.json and apps/web/openapi.json regenerated"

# Fail when the committed schema no longer matches the code. The endpoint
# inventory is a contract clients are written against; three endpoints were added
# and the committed document went stale without anything noticing.
#
# Compares against a regenerated copy rather than using `git diff`, so the result
# means "the file disagrees with the code" and not "the file has uncommitted edits".
openapi-check:
	@tmp=$$(mktemp -d); \
	uv run python -c "import json, pathlib, sys; from api.main import app; \
	pathlib.Path(sys.argv[1]).write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + '\n')" $$tmp/openapi.json; \
	if ! diff -q openapi.json $$tmp/openapi.json >/dev/null; then \
	  echo ">> openapi.json is stale — run 'make openapi' and commit the result"; \
	  diff -u openapi.json $$tmp/openapi.json | head -40; rm -rf $$tmp; exit 1; \
	fi; \
	if ! diff -q apps/web/openapi.json $$tmp/openapi.json >/dev/null; then \
	  echo ">> apps/web/openapi.json has drifted from the root copy"; rm -rf $$tmp; exit 1; \
	fi; \
	rm -rf $$tmp; echo ">> openapi.json is in sync with the code"
