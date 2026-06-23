# Document IA API

Technical README for the API subproject: setup, configuration, build, and useful commands.

## Documentation API

- **API summary (entry point)**: [docs/API_SUMMARY.md](./docs/API_SUMMARY.md)

## Prerequisites

- Python 3.13
- Poetry 2.x
- Redis
- PostgreSQL
- S3/MinIO compatible storage

## Installation

```bash
cd document-ia-api
poetry install
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

The API also depends on shared monorepo settings (PostgreSQL, Redis, S3, logging). Use the repository root `env.example` as reference.

## Run

Local start:

```bash
cd document-ia-api
poetry run python src/document_ia_api/main.py
```

Uvicorn alternative:

```bash
cd document-ia-api
poetry run uvicorn src.document_ia_api.main:app --host 0.0.0.0 --port 8000 --reload
```

OpenAPI documentation:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Database migrations

```bash
cd document-ia-api
poetry run alembic upgrade head
poetry run alembic downgrade -1
```

## Quality and tests

```bash
cd document-ia-api
poetry run pytest
poetry run ruff check src tests
poetry run pyright
```

## Build package

```bash
cd document-ia-api
poetry build
```
