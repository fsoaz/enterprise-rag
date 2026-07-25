.PHONY: lint typecheck test format install web-lint web-typecheck up down migrate seed

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
