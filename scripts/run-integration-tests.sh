#!/usr/bin/env bash
set -euo pipefail

test_db="${TEST_DATABASE_NAME:-enterprise_rag_test}"
if [[ ! "$test_db" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "Refusing database '$test_db': only letters, numbers, and underscores are allowed" >&2
  exit 2
fi
case "$test_db" in
  test_*|*_test) ;;
  *)
    echo "Refusing database '$test_db': test database names must start with test_ or end in _test" >&2
    exit 2
    ;;
esac

compose=(docker compose -f infra/compose/docker-compose.yml)
psql_cmd=("${compose[@]}" exec -T -e PGPASSWORD=postgres postgres psql -U postgres)
publish_port="${POSTGRES_PUBLISH_PORT:-15432}"
export POSTGRES_PUBLISH_PORT="$publish_port"
export REDIS_PUBLISH_PORT="${REDIS_PUBLISH_PORT:-16379}"
# This workflow validates service wiring, not semantic quality. Keep it offline and
# deterministic; real BGE is exercised by the explicit eval/deployment profile.
export INFERENCE_BACKEND=stub

cleanup() {
  "${psql_cmd[@]}" -d postgres -q \
    -c "DROP DATABASE IF EXISTS \"$test_db\" WITH (FORCE);" >/dev/null
}
trap cleanup EXIT

"${compose[@]}" up -d --wait postgres redis inference
"${psql_cmd[@]}" -d postgres -q \
  -c "DROP DATABASE IF EXISTS \"$test_db\" WITH (FORCE);" \
  -c "CREATE DATABASE \"$test_db\";"
"${psql_cmd[@]}" -d "$test_db" -v ON_ERROR_STOP=1 \
  -f /docker-entrypoint-initdb.d/01-init.sql >/dev/null

export TEST_DATABASE_URL="postgresql+asyncpg://rag_app:rag_app@localhost:${publish_port}/${test_db}"
export TEST_DATABASE_URL_MIGRATE="postgresql+psycopg://rag_migrate:rag_migrate@localhost:${publish_port}/${test_db}"
export DATABASE_URL="$TEST_DATABASE_URL"
export DATABASE_URL_MIGRATE="$TEST_DATABASE_URL_MIGRATE"
export DATABASE_URL_MAINT="postgresql+asyncpg://rag_maint:rag_maint@localhost:${publish_port}/${test_db}"
export REDIS_URL="redis://localhost:${REDIS_PUBLISH_PORT}/0"
export INFERENCE_BASE_URL="${INFERENCE_BASE_URL:-http://localhost:8001}"
export INFERENCE_SERVICE_TOKEN="${INFERENCE_SERVICE_TOKEN:-dev-inference-token}"
export DEV_AUTH_BYPASS=true

uv run alembic -c packages/db/alembic.ini upgrade head
uv run python -m db.seed
uv run pytest -q -m integration
