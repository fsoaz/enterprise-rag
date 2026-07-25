.PHONY: lint typecheck test format install web-lint web-typecheck up down migrate migrate-check seed

# Throwaway database for migrate-check. Never the dev database.
MIGRATE_CHECK_DB ?= rag_migrate_check
PSQL = docker compose -f infra/compose/docker-compose.yml exec -T -e PGPASSWORD=postgres postgres psql -U postgres

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

up:
	docker compose -f infra/compose/docker-compose.yml up -d --build postgres redis minio minio-init keycloak
	@echo "Waiting for Postgres..."
	@until docker compose -f infra/compose/docker-compose.yml exec -T postgres pg_isready -U postgres -d enterprise_rag >/dev/null 2>&1; do sleep 1; done
	$(MAKE) migrate
	$(MAKE) seed
	docker compose -f infra/compose/docker-compose.yml up -d --build api worker inference web

down:
	docker compose -f infra/compose/docker-compose.yml down

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
