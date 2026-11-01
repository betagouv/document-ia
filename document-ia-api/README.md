# Document IA API

Technical README for the API subproject: setup, configuration, build, and useful commands.

## Documentation API

- **API summary (entry point)**: [docs/API_SUMMARY.md](./docs/API_SUMMARY.md)

## Prerequisites

- Python 3.13
- UV 0.11.x
- Redis
- PostgreSQL
- S3/MinIO compatible storage

## Installation

```bash
cd document-ia-api
uv sync
```

## Environment variables

Main API variables:

| Variable | Default | Description |
|---|---:|---|
| `HOST` | `0.0.0.0` | HTTP server host |
| `PORT` | `8000` | HTTP server port |
| `BASE_URL` | `""` | External API base URL |
| `AUTO_MIGRATE` | `true` | Run Alembic migrations on startup |
| `APP_ENV` | `prod` | Runtime environment (also affects API key format) |
| `API_KEY_VERSION` | `1` | API key format version |
| `API_KEY_PEPPER_HASH` | `default_pepper_hash_value` | Pepper used to hash API keys |
| `API_KEY_PEPPER_CHK` | `default_pepper_chk_value` | Pepper used for API key checksum |
| `DOCUMENT_IA_API_KEY` | `""` | Internal/service API key |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `300` | Per-minute limit per API key |
| `RATE_LIMIT_REQUESTS_PER_DAY` | `5000` | Per-day limit per API key |
| `SYNC_EXECUTION_TIMEOUT_SECONDS` | `30` | Soft timeout for sync endpoints |
| `SYNC_EXECUTION_MAX_WAIT_SECONDS` | `60` | Hard max blocking time for sync endpoints |
| `SYNC_EXECUTION_POLL_INTERVAL_MS` | `250` | Event Store polling interval |
| `LOKI_URL` | `""` | Loki push endpoint (`/loki/api/v1/push`) |
| `LOKI_LOGGING_ENABLED` | `true` | Enable Loki log ingestion |
| `LOKI_BEARER_TOKEN` | unset | Optional Bearer token for Loki push. Use the raw token only, without the `Bearer ` prefix. Leave empty to push without authentication. |

The API also depends on shared monorepo settings (PostgreSQL, Redis, S3, logging). Use the repository root `env.example` as reference.

## Run

Local start:

```bash
cd document-ia-api
uv run python src/document_ia_api/main.py
```

Enable Uvicorn's automatic reload during local development with the `--reload`
flag:

```bash
cd document-ia-api
uv run python src/document_ia_api/main.py --reload
```

Uvicorn alternative:

```bash
cd document-ia-api
uv run uvicorn src.document_ia_api.main:app --host 0.0.0.0 --port 8000 --reload
```

OpenAPI documentation:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Redis webhook consumer ownership

`SimpleStreamConsumer` keeps its sequential async handler and simple `XREAD` cursor mode, or grouped `XREADGROUP`/ACK/recovery mode. It shares infra `StreamDelivery` group/read/claim/heartbeat and atomic copy-before-ACK primitives with the worker, **not** a universal base consumer or worker thread executor. Grouped delivery protects the entire fetched batch (up to `count`) plus claimed work with heartbeat refresh, including shutdown drain. Decode/unexpected handler errors remain pending in grouped mode; simple mode advances its cursor as before. With `auto_ack=False`, grouped reads do not start recovery/heartbeat tasks.

`WebhookErrorPolicy` alone implements inline HTTP retries/backoff: 400/401/403/422 are terminal; other 4xx/5xx can retry. HTTP `max_retries` counts extra inline attempts, while reclaimed Redis entries use the separate total-attempt budget. Terminal HTTP failures ACK only after confirmed DLQ retention; uncertain scan/write state stays pending. Atomic shared writes prevent competing reclaimers from creating duplicate copies after a lost reply or failed ACK. Existing scan preflights are fail-closed; retained history must not be trimmed before pending recovery completes.

Consumers and publishers borrow the process's `RedisManager`; stopping a consumer never closes that shared pool. FastAPI lifespan stops the webhook consumer (including recovery/heartbeat), then closes the application manager/client/pool. Workflow CPU/blocking operations stay in the worker's bounded thread executor; see its README for the PDF/PIL/model/boto/database blocking inventory. This refactor preserves current bounded shutdown behavior and does not add no-progress deadlines or exactly-once business-side-effect guarantees.

## Database migrations

```bash
cd document-ia-api
uv run alembic upgrade head
uv run alembic downgrade -1
```

Analytics note:
- On startup, the API runs both:
  - `auto_migrate()` for the main database,
  - `auto_migrate_analytics()` for the analytics database when `ANALYTICS_*` is configured.
- If `ANALYTICS_*` is missing, analytics migration is skipped (explicit log message).
- Operationally, in PaaS environments, ensure the API starts at least once with valid `ANALYTICS_*` before enabling the worker replication schedule.

## Quality and tests

### Saturation responses

All four v1/v2 execution and synchronous-execution routes check admission before
storing uploads in S3 or writing start events. Publication rechecks and allocates capacity
atomically, so preflight success is not a reservation. A race that saturates the
queue after preflight follows the existing #120 compensation: return 503,
attempt to record terminal scheduling failure and retain any uploaded file.

Client quota exhaustion returns **429** with `Retry-After` until the relevant
quota reset. Unavailable quota checks, queue saturation or failed admission
inspection return **503** with bounded `Retry-After` (default 5 seconds). They do
not disable rate limiting. RFC 7807 responses preserve this header. Result reads
are not admission- or quota-gated and remain available when Redis/processing is
degraded, provided their own database/authentication dependencies are available.

See [infra admission policy](../document-ia-infra/README.md#new-execution-admission)
for thresholds, recovery semantics and deployment limits. Redis connection/ping,
admission and quota commands have five-second deadlines per attempt; consumer
blocking reads retain their own longer blocking budget. Later requests retry
after an exhausted connection budget instead of remaining permanently disconnected.

```bash
cd document-ia-api
uv run pytest
uv run ruff check src tests
uv run pyright
```

## Production & Deployment (Scalingo)

To force UV to install local packages (like `document-ia-infra` or `document-ia-schemas`) in non-editable mode (copying them physically into the environment) on Scalingo, set the following environment variable:

```bash
scalingo env-set UV_NO_EDITABLE=1
```

## Build package

```bash
cd document-ia-api
uv build
```
