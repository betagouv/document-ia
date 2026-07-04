# Document IA

[![Python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/downloads/)
[![Poetry](https://img.shields.io/badge/package%20manager-poetry-blue)](https://python-poetry.org/)
[![FastAPI](https://img.shields.io/badge/api-FastAPI-009688)](https://fastapi.tiangolo.com/)
[![Docker Compose](https://img.shields.io/badge/local-Docker%20Compose-2496ED)](https://docs.docker.com/compose/)
[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

Document IA is a backend stack for running document-processing workflows: files are uploaded through a FastAPI API, stored in S3-compatible storage, queued through Redis Streams, processed by an asynchronous worker, and tracked in a PostgreSQL Event Store.

The repository is organized as a Python monorepo with separate packages for the API, worker, shared infrastructure code, document schemas, and evaluation tools.

## Quickstart

Prerequisites:

- Python 3.13
- Poetry 2.x
- Docker Compose

Create your local environment file:

```bash
cp env.example .env
```

Start the local infrastructure services:

```bash
docker compose up -d
```

This starts PostgreSQL, Redis, MinIO, MockServer, and the MinIO bucket initialization service.

Run the API in one terminal:

```bash
cd document-ia-api
poetry install
poetry run python src/document_ia_api/main.py
```

Run the worker in another terminal:

```bash
cd document-ia-worker
poetry install
poetry run python src/document_ia_worker/main.py
```

Optional: run the evaluation app in a third terminal:

```bash
cd document-ia-evals
poetry install
poetry run streamlit run src/document_ia_evals/app.py
```

Useful local URLs:

- API Swagger UI: `http://localhost:8000/docs`
- API ReDoc: `http://localhost:8000/redoc`
- MinIO console: `http://localhost:9001`
- Streamlit evals: `http://localhost:8501`

## Index

- [How it works](#how-it-works)
- [Repository map](#repository-map)
- [Documentation map](#documentation-map)
- [Local infrastructure](#local-infrastructure)
- [Common tasks](#common-tasks)
- [Development](#development)
- [Testing and quality](#testing-and-quality)

## How It Works

The default execution path is:

1. A client calls the API to start a workflow execution.
2. The API validates the request, stores the uploaded file in S3/MinIO, records the initial event in PostgreSQL, and publishes a message to Redis.
3. The worker consumes the Redis message.
4. The worker resolves the workflow definition and executes its steps, such as download, preprocessing, OCR, LLM extraction, and result persistence.
5. Execution state and failures are published to the Event Store.
6. API clients can inspect workflow state and results through the API.

At a high level:

```text
Client
  -> FastAPI API
  -> S3/MinIO file storage
  -> Redis Stream
  -> Worker workflow steps
  -> PostgreSQL Event Store
```

## Repository Map

| Path | Role | Documentation |
|---|---|---|
| `document-ia-api` | FastAPI application, authentication, workflow endpoints, migrations | [document-ia-api/README.md](./document-ia-api/README.md) |
| `document-ia-worker` | Asynchronous workflow execution, Redis consumer, retries, DLQ, scheduled tasks | [document-ia-worker/README.md](./document-ia-worker/README.md) |
| `document-ia-schemas` | Pydantic document schemas used for extraction prompts and validation | [document-ia-schemas/README.md](./document-ia-schemas/README.md) |
| `document-ia-infra` | Shared infrastructure code used by API and worker | [document-ia-infra/README.md](./document-ia-infra/README.md) |
| `document-ia-evals` | Streamlit application for evaluating Document IA outputs | [document-ia-evals/README.md](./document-ia-evals/README.md) |
| `docker-compose.yml` | Local PostgreSQL, Redis, MinIO, MockServer, and S3 bucket setup | [docker-compose.yml](./docker-compose.yml) |
| `env.example` | Reference environment variables for local development | [env.example](./env.example) |

## Documentation Map

Start here depending on what you need:

| Need | Read |
|---|---|
| API setup, environment variables, run commands | [document-ia-api/README.md](./document-ia-api/README.md) |
| API architecture, routes, auth, error handling, workflow docs | [document-ia-api/docs/API_SUMMARY.md](./document-ia-api/docs/API_SUMMARY.md) |
| Database migration workflow | [document-ia-api/alembic/README.md](./document-ia-api/alembic/README.md) |
| Bruno API collection | [document-ia-api/bruno-api/README.md](./document-ia-api/bruno-api/README.md) |
| API test organization | [document-ia-api/tests/README.md](./document-ia-api/tests/README.md) |
| Worker execution flow, retries, DLQ, scheduler | [document-ia-worker/README.md](./document-ia-worker/README.md) |
| Document schema package and supported document types | [document-ia-schemas/README.md](./document-ia-schemas/README.md) |
| Evaluation app | [document-ia-evals/README.md](./document-ia-evals/README.md) |
| Evaluation metrics | [document-ia-evals/METRICS.md](./document-ia-evals/METRICS.md) |

## Local Infrastructure

Start services:

```bash
docker compose up -d
```

Check status:

```bash
docker compose ps
docker compose exec postgres pg_isready
docker compose exec redis redis-cli ping
```

View logs:

```bash
docker compose logs
docker compose logs -f
docker compose logs postgres
docker compose logs redis
docker compose logs minio
```

Stop services:

```bash
docker compose down
```

MinIO provides local S3-compatible storage:

- API endpoint: `http://localhost:9000`
- Console: `http://localhost:9001`
- Default bucket: configured through `S3_BUCKET_NAME`

The `init-s3-bucket` Docker Compose service creates the configured bucket after MinIO becomes healthy. If you need to run only this initialization step again:

```bash
docker compose up init-s3-bucket
```

## Common Tasks

Run the API:

```bash
cd document-ia-api
poetry run python src/document_ia_api/main.py
```

Run the API with Uvicorn reload:

```bash
cd document-ia-api
poetry run uvicorn src.document_ia_api.main:app --host 0.0.0.0 --port 8000 --reload
```

Run the worker:

```bash
cd document-ia-worker
poetry run python src/document_ia_worker/main.py
```

Run the evaluation app:

```bash
cd document-ia-evals
poetry run streamlit run src/document_ia_evals/app.py
```

Open the Bruno collection:

```bash
cd document-ia-api/bruno-api
bruno run workflows/execute.bru
```

Regenerate worker prompt snapshots after schema changes:

```bash
cd document-ia-worker
poetry run python tests/fixtures/regenerate_extraction_prompt_fixtures.py
```

## Development

Each subproject owns its Python environment and dependency lock file. Install dependencies from the package you are working on:

```bash
cd document-ia-api
poetry install
```

```bash
cd document-ia-worker
poetry install
```

```bash
cd document-ia-schemas
poetry install
```

When developing against shared local packages, install them in editable mode from the consuming package:

```bash
poetry run pip install -e ../document-ia-infra
poetry run pip install -e ../document-ia-schemas
```

## Testing and Quality

Run tests from the relevant package:

```bash
cd document-ia-api
poetry run pytest
poetry run ruff check src tests
poetry run pyright
```

```bash
cd document-ia-worker
poetry run pytest
poetry run ruff check src tests
```

```bash
cd document-ia-schemas
poetry run pytest
poetry run ruff check .
poetry run ruff format --check .
```

## License

MIT. See [LICENSE](./LICENSE).
