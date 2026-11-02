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
| `DOCUMENT_IA_API_KEY` | `""` | Initial `PlatformAdmin` organization API key (seeded during Alembic migration) |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `300` | Per-minute limit per API key |
| `RATE_LIMIT_REQUESTS_PER_DAY` | `5000` | Per-day limit per API key |
| `SYNC_EXECUTION_TIMEOUT_SECONDS` | `30` | Soft timeout for sync endpoints |
| `SYNC_EXECUTION_MAX_WAIT_SECONDS` | `60` | Hard max blocking time for sync endpoints |
| `SYNC_EXECUTION_POLL_INTERVAL_MS` | `250` | Event Store polling interval |
| `LOKI_URL` | `""` | Loki push endpoint (`/loki/api/v1/push`) |
| `LOKI_LOGGING_ENABLED` | `true` | Enable Loki log ingestion |
| `LOKI_BEARER_TOKEN` | unset | Optional Bearer token for Loki push. Use the raw token only, without the `Bearer ` prefix. Leave empty to push without authentication. |

The API also depends on shared monorepo settings (PostgreSQL, Redis, S3, logging, `WEBHOOK_SECRET_ENCRYPTION_KEY`). Use the repository root `env.example` and [document-ia-infra/README.md](../document-ia-infra/README.md) as references.

### Generating the initial Admin API key (`DOCUMENT_IA_API_KEY`)

During the initial Alembic migration, the API reads `DOCUMENT_IA_API_KEY` to seed the default `PlatformAdmin` organization (`Document IA Default Organization`) and its active API key in PostgreSQL.

> **Important:** Make sure `APP_ENV` (`dev`, `staging`, `sandbox`, or `prod`), `API_KEY_PEPPER_CHK`, and `API_KEY_PEPPER_HASH` are already set to their target environment values in your `.env` (or shell environment) **before** running the script, otherwise checksum verification will fail during migration or authentication.

Generate a valid API key from the repository root:

```bash
uv run --directory document-ia-api python scripts/generate_api_key.py
```

Or for a specific target environment/pepper without modifying your local `.env`:

```bash
APP_ENV=prod API_KEY_PEPPER_CHK="<target-chk-pepper>" API_KEY_PEPPER_HASH="<target-hash-pepper>" \
  uv run --directory document-ia-api python scripts/generate_api_key.py
```

Copy the `API key (presented)` value (`dia_<env>_<version>_<prefix>_<body>_<checksum>`) into your `.env` file (or deployment environment variables) before running migrations:

```dotenv
DOCUMENT_IA_API_KEY=<presented-api-key>
```

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
