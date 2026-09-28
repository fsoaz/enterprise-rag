# Run and troubleshoot local development

Start with the [README prerequisites and Compose setup](../../README.md#getting-started).
This guide covers ports, development sign-in, running processes separately, the
deterministic evaluation, checking a first upload, and diagnosing failures. Run
commands from the repository root in Bash unless stated otherwise. Commands are
consistent with the inspected configuration.
[VERIFY] A full fresh-machine startup has not been executed as part of the
documentation updates; the Docker CLI was unavailable in the validation environment.

## Ports

Every published Compose port binds to `127.0.0.1` unless `BIND_ADDR` overrides it
(see [network exposure](../../README.md#network-exposure)). These host ports must be free:

| Service | Host port | Configurable in root `.env` |
| --- | --- | --- |
| Postgres | 15432 | `POSTGRES_PUBLISH_PORT` |
| Redis | 16379 | `REDIS_PUBLISH_PORT` |
| MinIO API / console | 19000 / 19001 | `MINIO_API_PUBLISH_PORT` / `MINIO_CONSOLE_PUBLISH_PORT` |
| Keycloak | 8080 | no |
| API | 8000 | no |
| Inference | 8001 | no |
| Web | 3000 | no |

If you change a publish port, also change the matching URLs in `.env`
(`DATABASE_URL*`, `REDIS_URL`, `CELERY_*`, `S3_ENDPOINT_URL`). Compose reads these
values only through `--env-file`; see [Compose ignores `.env`](#compose-ignores-env-values).

## Development sign-in

The default path is OIDC Authorization Code + PKCE against the imported
`enterprise-rag` Keycloak realm. Open `http://localhost:3000` and choose **Sign in**.
Use `localhost` consistently: the development OIDC issuer and callback configuration
use that host. Every seeded identity's password equals its username.

| Username | Tenant | Role | Groups | Sees the seeded collection |
| --- | --- | --- | --- | --- |
| `acme-admin` | Acme | admin (manages ACL entries; bypasses ACL within its tenant) | engineering, legal | yes |
| `acme-steward` | Acme | steward (uploads and archives documents) | engineering | yes |
| `acme-member` | Acme | member (read-only) | engineering | yes |
| `acme-viewer` | Acme | viewer (read-only) | legal | no |
| `globex-admin` | Globex | admin | ops, finance | yes |
| `globex-steward` | Globex | steward | ops | yes |
| `globex-member` | Globex | member | ops | yes |
| `globex-viewer` | Globex | viewer | finance | no |

The seeded collections are **Acme Policies** and **Globex Runbooks**. Each grants
access to one group (`engineering` and `ops` respectively), so the viewers see
neither collection until an admin adds an ACL entry. Seeding creates identities,
collections, and ACLs; it does not ingest documents.

The realm and the database seed share stable tenant UUIDs. `make seed`, which
`make up` runs, remaps an existing tenant's ID to the stable value, so an older
development database does not need a reset to match the realm.

### Header-based impersonation (bypass)

> **`DEV_AUTH_BYPASS=true` trusts the impersonation header with no verification — any
> caller can become any user, in any tenant.** Use it only on a development machine.

Compose hardcodes the bypass off for the API, so this mode needs the
[separate-process workflow](#run-processes-separately). Set, then restart the API and web:

| File | Setting |
| --- | --- |
| root `.env` | `DEV_AUTH_BYPASS=true` and `CORS_ALLOW_ORIGINS=http://localhost:3000` |
| `apps/web/.env.local` | `NEXT_PUBLIC_DEV_AUTH=true` |

In this mode the browser calls FastAPI directly and identifies the user with
`X-Dev-User: <username>`. The API also accepts `Authorization: Bearer dev:<username>`.

## Run processes separately

Use this workflow when editing Python services, using web hot reload, or using the
authentication bypass. If the full stack is already running, stop it with
`make down` before starting this workflow to free its ports. That command retains
Compose volumes.

For a fresh checkout, create configuration files:

```bash
cp .env.example .env
cp apps/web/.env.example apps/web/.env.local
```

Keep existing files if already configured. The root example configures host
connections to the Compose data services. Leave the Anthropic key placeholder
unchanged for degraded, no-generation operation, or set your own key to enable
generation. See [configuration loading](#configuration-loading).

Install dependencies, start the supporting services, and wait for Postgres:

```bash
uv sync --all-packages --group dev
npm ci --prefix apps/web
docker compose --env-file .env -f infra/compose/docker-compose.yml up -d postgres redis minio minio-init keycloak
until docker compose --env-file .env -f infra/compose/docker-compose.yml exec -T postgres pg_isready -U postgres -d enterprise_rag; do sleep 1; done
```

Then migrate, seed, and install the model runtime:

```bash
make migrate
make seed
uv sync --all-packages --all-extras --group dev
```

The last command installs the inference `models` extra, including the real BGE
runtime. Initial downloads and model loading can take more than ten minutes;
duration depends on network access and host resources. The default device is CPU.

Run each of the following in its own terminal at the repository root. Leave each
process running. `--no-sync` uses the environment installed above without changing
dependencies while other services are running.

Inference:

```bash
uv run --no-sync --env-file .env uvicorn inference.main:app --host 127.0.0.1 --port 8001
```

API:

```bash
uv run --no-sync --env-file .env uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

Worker:

```bash
uv run --no-sync --env-file .env celery -A worker.celery_app.celery_app worker --loglevel=INFO
```

Web:

```bash
npm run dev --prefix apps/web
```

Stop each local process with Ctrl+C, then run `make down` to stop the supporting
services. If you change dependencies, stop the Python processes, sync again, and
restart them.

## Configuration loading

| Runtime | Configuration source |
| --- | --- |
| Compose | The Makefile passes root `.env` for interpolation; API and worker also receive it through `env_file`. Explicit service `environment` entries override that file. Inference and web receive only the settings wired in Compose. |
| Local Python commands above | `uv run --env-file .env` loads root configuration into the process environment. Existing exported variables take precedence. |
| API settings | Pydantic also reads root `.env`, but that does not export its values to shared libraries that use `os.environ`. |
| Local web | Next.js reads `apps/web/.env.local`. Browser-visible `NEXT_PUBLIC_*` values are compiled into its bundle. |

Keep [.env.example](../../.env.example) and
[apps/web/.env.example](../../apps/web/.env.example) as the configuration templates.
Copying a file does not export it to a shell. Inference reads its token, backend,
device, and model names from the process environment. Without
`INFERENCE_SERVICE_TOKEN`, its model routes accept unauthenticated requests; with
it, callers must send the matching bearer token. Use the environment-loading
commands above for API, worker, inference, and evaluation commands.

Model selection:

| Setting | Read by | Notes |
| --- | --- | --- |
| `EMBEDDING_MODEL_NAME`, then `EMBEDDING_MODEL` | inference, API, worker | The first one set wins. Together with `INFERENCE_BACKEND`, it selects the stored embedding generation retrieval uses. The vector dimension is fixed at 1024. |
| `EMBEDDING_MODEL_VERSION` | API, worker | Optional override. By default the version derives from `INFERENCE_BACKEND` (`stub` → `stub-v0`, `bge` → `bge-v1`). |
| `RERANK_MODEL` | inference | |
| `INFERENCE_BACKEND` | inference, API, worker | `bge` (default) or `stub` (deterministic wiring profile). |
| LLM models | code | Selected in `packages/llm/src/llm/models.py`, not through environment variables. |

Under Compose, the inference service receives only `INFERENCE_BACKEND`,
`INFERENCE_DEVICE`, and its service token; the model-name settings in `.env` do not
reach it, so it uses its built-in BGE-M3 and BGE-reranker-v2-m3 defaults.

## Run the deterministic evaluation locally

T-407 uses the same API, Celery worker, database, Redis, and inference service
path as production, with `INFERENCE_BACKEND=stub` for reproducibility. The harness
authenticates with the `X-Dev-User` header and loads the synthetic corpus into the
`acme` tenant of whatever database `DATABASE_URL` names, so it needs the
[separate-process workflow](#run-processes-separately) with the bypass enabled; the
Compose API rejects it. Use a disposable database, not `enterprise_rag`.

With the supporting Compose services running, create and prepare a disposable
database. Its name must start with `test_` or end in `_test`:

```bash
docker compose --env-file .env -f infra/compose/docker-compose.yml exec -T -e PGPASSWORD=postgres postgres \
  psql -U postgres -q -c "DROP DATABASE IF EXISTS enterprise_rag_eval_test WITH (FORCE);" -c "CREATE DATABASE enterprise_rag_eval_test;"
docker compose --env-file .env -f infra/compose/docker-compose.yml exec -T -e PGPASSWORD=postgres postgres \
  psql -U postgres -d enterprise_rag_eval_test -v ON_ERROR_STOP=1 -q -f /docker-entrypoint-initdb.d/01-init.sql
```

In every terminal used below (inference, API, worker, and the harness), export the
evaluation settings. Exported variables take precedence over `--env-file .env`:

```bash
export DATABASE_URL=postgresql+asyncpg://rag_app:rag_app@localhost:15432/enterprise_rag_eval_test
export DATABASE_URL_MIGRATE=postgresql+psycopg://rag_migrate:rag_migrate@localhost:15432/enterprise_rag_eval_test
export DATABASE_URL_MAINT=postgresql+asyncpg://rag_maint:rag_maint@localhost:15432/enterprise_rag_eval_test
export INFERENCE_BACKEND=stub
export INFERENCE_SERVICE_TOKEN=dev-inference-token
export DEV_AUTH_BYPASS=true
export TENANT_DAILY_BUDGET_USD=0
```

`TENANT_DAILY_BUDGET_USD=0` disables the budget guard, as CI does. Then migrate and
seed the disposable database, start inference, the API, and the worker with the
commands from [Run processes separately](#run-processes-separately), and run the
smoke comparison:

```bash
uv run --no-sync --env-file .env alembic -c packages/db/alembic.ini upgrade head
uv run --no-sync --env-file .env python -m db.seed
```

```bash
uv run --no-sync --env-file .env python -m evals.harness.ci \
  --mode smoke \
  --output /tmp/eval-smoke.json
uv run --no-sync --env-file .env python -m evals.harness.gate \
  --report /tmp/eval-smoke.json \
  --baseline evals/baselines/t407-smoke.json \
  --output /tmp/eval-gate.json
```

The harness calls `http://127.0.0.1:8000/api/v1` unless `EVAL_API_URL` is set.
The hosted job's full environment is in the
[`eval-smoke` job](../../.github/workflows/ci.yml).

The smoke run validates the complete committed dataset before selecting six
items from each of its eight slices, for 48 items across the four configured
retrieval strategies. A successful gate means the report is compatible with
the committed dataset/configuration and stays within the Phase 4 quality and
zero-tolerance security thresholds. It does not measure live Anthropic answer
quality or incur paid model calls.

To exercise the complete scheduled path locally, replace `--mode smoke` with
`--mode full` and write to a separate output file. The hosted equivalents are
the [`eval-smoke` job](../../.github/workflows/ci.yml), which runs on pull requests
and pushes to `main`, and the scheduled
[`eval-full` workflow](../../.github/workflows/eval-full.yml); their artifacts
contain the comparison report and service logs needed for review.

Drop the disposable database when finished:

```bash
docker compose --env-file .env -f infra/compose/docker-compose.yml exec -T -e PGPASSWORD=postgres postgres \
  psql -U postgres -q -c "DROP DATABASE IF EXISTS enterprise_rag_eval_test WITH (FORCE);"
```

## Verify startup

With either startup workflow running:

```bash
curl --fail --silent --show-error http://localhost:8001/ready
curl --fail --silent --show-error http://localhost:8000/health
curl --fail --silent --show-error http://localhost:8000/ready
curl --fail --silent --show-error --output /dev/null http://localhost:8080/realms/enterprise-rag/.well-known/openid-configuration
curl --fail --silent --show-error --output /dev/null http://localhost:3000
```

Inference responds with `{"status":"ready"}` after both models load. API liveness
returns `{"status":"ok"}`. API readiness returns HTTP 200 when its database, Redis,
and inference checks pass; otherwise it returns HTTP 503 with per-dependency
`checks`. Readiness does not test the worker, object storage, Keycloak, or
Anthropic; the last two commands check that the Keycloak realm and the web server
respond.

Sign in with a [seeded identity](#development-sign-in). The interactive API
reference is at `http://localhost:8000/api/docs`.

## Verify an upload

On a fresh database:

1. Sign in as the seeded `acme-steward` identity and open `http://localhost:3000/admin`.
2. Select **Acme Policies** and upload the repository fixture
   [hr_remote_work_v2.md](../../evals/fixtures/hr_remote_work_v2.md).
3. Check the displayed ingestion status. Use **View jobs** in the English UI to
   inspect the document's job history. Processing may outlast the initial polling
   window; reload the page and inspect the jobs again.
4. Confirm a job reaches `succeeded`. A `202` upload response alone is insufficient.
5. Open chat and ask how many days per week employees may work remotely. Inspect
   the cited policy passage. With no usable Anthropic key, the system uses its
   degraded response path; do not expect a synthesized, `grounded` answer.

The fixture says three days per week, agreed with the reporting manager. An answer
quality check requires inspecting the response and citations; ingestion success
alone does not establish answer quality. If this fixture is already the current
version of a document in the collection, the duplicate-content check returns 409.
Inspect the existing document and job instead of repeating the upload.

For direct API clients, see [upload responses and job polling](../standards/api_rules.md#8-long-running-operations).

## Reset and clean up

| Goal | Command | Effect |
| --- | --- | --- |
| Stop the stack | `make down` | Keeps all volumes. |
| Rebuild the development database | `make db-reset` | Drops `enterprise_rag` with `WITH (FORCE)`, which terminates live API and worker connections; re-migrates and re-seeds. Requires the Compose Postgres container. Object-storage and model volumes are kept. |
| Remove all local data | `docker compose --env-file .env -f infra/compose/docker-compose.yml down -v` | Deletes every Compose volume, including the database, MinIO objects, and the downloaded model cache. |

Run `make db-reset` before quoting manual authorization or retrieval results.
Integration tests write into whatever database `DATABASE_URL` points at; ACL rows
and documents left behind change what users can see and what retrieval returns.
`make db-reset` does not load documents; reload the evaluation fixtures with
`uv run --no-sync --env-file .env python -m evals.harness.run --load-corpus`.

## Troubleshooting

### Upload stays pending

**Symptom:** The upload is accepted, but the job remains `pending`.

**Likely cause:** Redis accepted the task, but no worker is consuming it. The
inline fallback handles publishing failures; a missing consumer does not trigger it.

**Verification:** Inspect the worker terminal, or for the full Compose workflow:

```bash
docker compose --env-file .env -f infra/compose/docker-compose.yml ps worker
docker compose --env-file .env -f infra/compose/docker-compose.yml logs --tail=100 worker
```

**Resolution:** Start the local worker command above, or start the Compose worker:

```bash
docker compose --env-file .env -f infra/compose/docker-compose.yml up -d worker
```

The worker can consume the queued task if it remains in the configured broker.
Ensure API and worker use the same `CELERY_BROKER_URL`. Check job history for a
terminal state; uploading the same bytes again can return 409.

### Inference does not become ready

**Symptom:** Port 8001 is unavailable, API readiness reports `inference: false`,
or `make up` stops because the `inference` container is unhealthy.

**Likely cause:** Models are still loading, model downloads failed, or the local
environment lacks the inference `models` extra. Startup fails if real models
cannot load; it does not silently switch to stub embeddings. Compose allows
inference a 10-minute start period plus ten 5-second health retries; API and worker
wait for it to be healthy, so a first model download that takes longer makes
`make up` fail.

**Verification:** Inspect the inference terminal, or:

```bash
docker compose --env-file .env -f infra/compose/docker-compose.yml logs --tail=100 inference
```

**Resolution:** If loading is progressing, wait and retry the readiness probe, or
run `make up` again: Compose keeps downloaded weights in the `inference_models`
volume, so a second start is faster. For missing local dependencies, stop the
Python processes and repeat the `uv sync --all-packages --all-extras --group dev`
installation. Resolve download or resource errors reported in the logs, then
restart inference.

### Inference switched to the stub after integration tests

**Symptom:** After `make test-integration`, the Compose stack's retrieval quality
drops or requests fail with a model identity mismatch.

**Likely cause:** The integration script exports `INFERENCE_BACKEND=stub` and runs
`docker compose up` for `inference`, which recreates the shared inference container
with the deterministic stub backend. API and worker processes still expect the BGE
embedding version (`bge-v1`); the stub reports `stub-v0`.

**Verification:** Ask inference which embedding identity it serves:

```bash
curl --silent --show-error -X POST http://localhost:8001/v1/embed \
  -H "Authorization: Bearer dev-inference-token" -H "Content-Type: application/json" \
  -d '{"texts": ["identity check"]}' \
  | python3 -c 'import json, sys; body = json.load(sys.stdin); print(body["model"], body["version"])'
```

**Resolution:** Run `make up` again; it recreates inference with the backend from
`.env`. Re-ingest documents processed while the stub was active.

### Ingestion fails

**Symptom:** Job status is `failed`.

**Likely cause:** The pipeline recorded a parsing, storage, embedding, or indexing
failure. The job's `stage` and `error` narrow the diagnosis.

**Verification:** Inspect job history and worker logs. For storage failures, check
MinIO availability and the S3 settings loaded into the API and worker. For model
failures, run the inference readiness probe and check matching service tokens.

**Resolution:** Correct the reported dependency or input error before attempting
new work. No ingestion retry endpoint is implemented. A failed upload may leave
document/version rows, and re-uploading identical bytes may return 409. See
[Reset and clean up](#reset-and-clean-up) before using `make db-reset`; it is not
a per-document retry.

### API readiness reports database or Redis failure

**Symptom:** `/ready` returns HTTP 503 with `database: false` or `redis: false`.

**Likely cause:** The service is down or the API loaded a URL pointing to the
wrong host or port.

**Verification:** Inspect the readiness JSON without curl's `--fail` option and
check the supporting services:

```bash
curl --silent --show-error http://localhost:8000/ready
docker compose --env-file .env -f infra/compose/docker-compose.yml ps postgres redis
```

**Resolution:** Start the missing service and align root `.env` with published
ports for local processes. Container processes use the internal hosts and ports
configured in Compose. Restart local processes after changing their environment.

### Compose ignores `.env` values

**Symptom:** A publish port or `BIND_ADDR` set in root `.env` has no effect.

**Likely cause:** The Compose project directory is `infra/compose/`, so Compose
does not read root `.env` for `${VAR}` interpolation unless `--env-file .env` is
passed. The Makefile and the commands in this guide pass it.
`scripts/run-integration-tests.sh` (`make test-integration`) and `make migrate-check`
read publish ports from the shell environment only.

**Resolution:** Pass `--env-file .env` to direct `docker compose` commands. For
`make test-integration` and `make migrate-check` with non-default ports, export
`POSTGRES_PUBLISH_PORT` (and `REDIS_PUBLISH_PORT` for integration tests) in the shell.
`make test-integration` uses the database `enterprise_rag_test` unless
`TEST_DATABASE_NAME` names another `test_*` or `*_test` database.
