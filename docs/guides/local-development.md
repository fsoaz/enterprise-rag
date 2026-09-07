# Run and troubleshoot local development

Start with the [README prerequisites and Compose setup](../../README.md#getting-started).
This guide covers running processes separately, checking a first upload, and
diagnosing failures. Run commands from the repository root in Bash unless stated
otherwise. Commands are consistent with the inspected configuration.
[VERIFY] A full fresh-machine startup has not been executed as part of this
documentation update; the Docker CLI is unavailable in the validation environment.

## Run processes separately

Use this workflow when editing Python services or using web hot reload. If the
full stack is already running, stop it with `make down` before starting this
workflow to free its ports. That command retains Compose volumes.

For a fresh checkout, create configuration files:

```bash
cp .env.example .env
cp apps/web/.env.example apps/web/.env.local
```

Keep existing files if already configured. The root example configures host
connections to the Compose data services. Leave the Anthropic key placeholder
unchanged for degraded, no-generation operation, or set your own key to enable
generation. See [configuration loading](#configuration-loading).

Install dependencies and start the supporting services:

```bash
uv sync --all-packages --group dev
npm ci --prefix apps/web
docker compose --env-file .env -f infra/compose/docker-compose.yml up -d postgres redis minio minio-init keycloak
docker compose --env-file .env -f infra/compose/docker-compose.yml exec -T postgres pg_isready -U postgres -d enterprise_rag
```

Wait for `pg_isready` to report that Postgres accepts connections before continuing:

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
and device from process environment. Without `INFERENCE_SERVICE_TOKEN`, its model
routes accept unauthenticated requests; with it, callers must send the matching
bearer token. Use the environment-loading commands above for API, worker, inference,
and local evaluation commands.

For optional header-based development authentication, follow the
[README settings](../../README.md#dev-auth-and-network-exposure). Compose forces
the bypass off; use the separate-process workflow for this mode.

## Run the deterministic evaluation locally

T-407 uses the same API, Celery worker, database, Redis, and inference service
path as production, with `INFERENCE_BACKEND=stub` for reproducibility. Use only
the synthetic corpus and a disposable database. Start the services above, or
use the equivalent Compose/CI service setup. For the separate-process workflow,
set the deterministic and development-auth settings before starting inference,
the API, and the worker:

```bash
export INFERENCE_BACKEND=stub
export INFERENCE_SERVICE_TOKEN=dev-inference-token
export DEV_AUTH_BYPASS=true
```

Then run the smoke comparison:

```bash
uv run python -m evals.harness.ci \
  --mode smoke \
  --output /tmp/eval-smoke.json
uv run python -m evals.harness.gate \
  --report /tmp/eval-smoke.json \
  --baseline evals/baselines/t407-smoke.json \
  --output /tmp/eval-gate.json
```

The smoke run validates the complete committed dataset before selecting six
items from each of its eight slices, for 48 items across the four configured
retrieval strategies. A successful gate means the report is compatible with
the committed dataset/configuration and stays within the Phase 4 quality and
zero-tolerance security thresholds. It does not measure live Anthropic answer
quality or incur paid model calls.

To exercise the complete scheduled path locally, replace `--mode smoke` with
`--mode full` and write to a separate output file. The hosted equivalents are
the [`eval-smoke` job](../../.github/workflows/ci.yml) and the scheduled
[`eval-full` workflow](../../.github/workflows/eval-full.yml); their artifacts
contain the comparison report and service logs needed for review.

## Verify startup

With either startup workflow running:

```bash
curl --fail --silent --show-error http://localhost:8001/ready
curl --fail --silent --show-error http://localhost:8000/health
curl --fail --silent --show-error http://localhost:8000/ready
```

Inference responds with `{"status":"ready"}` after both models load. API liveness
returns `{"status":"ok"}`. API readiness returns HTTP 200 when its database, Redis,
and inference checks pass; otherwise it returns HTTP 503 with per-dependency
`checks`. Readiness does not test the worker, object storage, Keycloak, or Anthropic.

Open `http://localhost:3000` and sign in using a seeded development identity from
the [README](../../README.md#dev-auth-and-network-exposure). Use `localhost`
consistently: the development OIDC issuer and callback configuration use that host.
The interactive API reference is at `http://localhost:8000/api/docs`.

## Verify an upload

Seeding creates identities, collections, and ACLs; it does not ingest documents.
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
alone does not establish answer quality. If this fixture was already uploaded,
the duplicate-content check returns 409. Inspect the existing document and job
instead of repeating the upload.

For direct API clients, see [upload responses and job polling](../standards/api_rules.md#8-long-running-operations).

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

**Symptom:** Port 8001 is unavailable, or API readiness reports `inference: false`.

**Likely cause:** Models are still loading, model downloads failed, or the local
environment lacks the inference `models` extra. Startup fails if real models
cannot load; it does not silently switch to stub embeddings.

**Verification:** Inspect the inference terminal, or:

```bash
docker compose --env-file .env -f infra/compose/docker-compose.yml logs --tail=100 inference
```

**Resolution:** If loading is progressing, wait and retry the readiness probe.
For missing local dependencies, stop the Python processes and repeat the
`uv sync --all-packages --all-extras --group dev` installation. Resolve download
or resource errors reported in the logs, then restart inference. Compose retains
its model cache in the `inference_models` volume.

### Ingestion fails

**Symptom:** Job status is `failed`.

**Likely cause:** The pipeline recorded a parsing, storage, embedding, or indexing
failure. The job's `stage` and `error` narrow the diagnosis.

**Verification:** Inspect job history and worker logs. For storage failures, check
MinIO availability and the S3 settings loaded into the API and worker. For model
failures, run the inference readiness probe and check matching service tokens.

**Resolution:** Correct the reported dependency or input error before attempting
new work. No ingestion retry endpoint is implemented. A failed upload may leave
document/version rows, and re-uploading identical bytes may return 409. A full
`make db-reset` is only appropriate for disposable local data: it destroys the
development database and re-seeds identities, but does not clear object-storage
volumes. Do not use it as a routine per-document retry.

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
