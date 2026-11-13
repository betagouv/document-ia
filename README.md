# Document IA

[![Python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/badge/package%20manager-uv-blue)](https://github.com/astral-sh/uv)
[![FastAPI](https://img.shields.io/badge/api-FastAPI-009688)](https://fastapi.tiangolo.com/)
[![Docker Compose](https://img.shields.io/badge/local-Docker%20Compose-2496ED)](https://docs.docker.com/compose/)
[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

Document IA is a backend stack for running document-processing workflows: files are uploaded through a FastAPI API, stored in S3-compatible storage, queued through Redis Streams, processed by an asynchronous worker, and tracked in a PostgreSQL Event Store.

The repository is organized as a Python monorepo with separate packages for the API, worker, shared infrastructure code, document schemas, and evaluation tools.

## Quickstart

Prerequisites:

- Python 3.13
- UV 0.11.x
- Docker Compose
- An [Albert API](https://albert.api.etalab.gouv.fr/) key for OCR and LLM calls (`OPENAI_*` in `.env`)

Create your local environment file:

```bash
cp env.example .env
```

Configure `.env` before starting the API (see [document-ia-api/README.md](./document-ia-api/README.md) for API key generation):

- `APP_ENV=dev`, `API_KEY_PEPPER_HASH`, `API_KEY_PEPPER_CHK`, and `DOCUMENT_IA_API_KEY` must be consistent (the admin org is seeded on first migration).
- `OPENAI_API_KEY` must be your **Albert** credential.
- Local Albert setup: `OPENAI_BASE_URL=https://albert.api.etalab.gouv.fr/v1`
- Leave `AUTO_MIGRATE=true` so Alembic runs when the API starts.

Start the local infrastructure services:

```bash
docker compose up -d
```

This starts PostgreSQL, Redis, MinIO, MockServer, and the MinIO bucket initialization service (`init-s3-bucket` creates the `document-ia` bucket then exits).

Run the API in one terminal:

```bash
cd document-ia-api
uv sync
uv run python src/document_ia_api/main.py
```

Run the worker in another terminal:

```bash
cd document-ia-worker
uv sync
uv run python src/document_ia_worker/main.py
```

On startup the worker may consume leftover Redis messages from local tests (some may land in the DLQ); this is normal in dev.

Check the API and admin key (trailing slash on the workflows URL):

```bash
export DIA_KEY=$(grep -E '^DOCUMENT_IA_API_KEY=' .env | cut -d= -f2-)
curl -s -H "X-API-KEY: $DIA_KEY" http://localhost:8000/api/v2/workflows/ | head
```

Optional: run the evaluation app in a third terminal:

```bash
cd document-ia-evals
uv sync
uv run streamlit run src/document_ia_evals/app.py
```

Useful local URLs:

- API Swagger UI: `http://localhost:8000/docs`
- API ReDoc: `http://localhost:8000/redoc`
- MinIO console: `http://localhost:9001`
- Streamlit evals: `http://localhost:8501`

### Smoke test: classify and extract a PDF

From the repository root, after API and worker are running:

```bash
export DIA_KEY=$(grep -E '^DOCUMENT_IA_API_KEY=' .env | cut -d= -f2-)

curl -s -X POST "http://localhost:8000/api/v2/workflows/document-classification-extraction-v2/execute" \
  -H "X-API-KEY: $DIA_KEY" \
  -F "file=@your-document.pdf;type=application/pdf" \
  -F 'override={"extract_content_ocr":[{"param":"model","value":"lightOn"}]}' \
  | python3 -m json.tool
```

Use the `execution_id` from the response, then poll results (add `?is_debug_mode=true` to inspect workflow metadata):

```bash
curl -s -H "X-API-KEY: $DIA_KEY" \
  "http://localhost:8000/api/v1/executions/<execution_id>?is_debug_mode=true"
```

For multi-page files or slow OCR, prefer `/execute` over `/execute-sync` (sync endpoints time out around 30s). Photo-based identity documents often need OCR `lightOn` rather than the default `mistral` model—otherwise extraction may succeed with hallucinated fields while OCR text is empty. Raw OCR text is only exposed in debug metadata when extraction runs (not when classification is `autre`); see [document-ia-api/docs/API_SUMMARY.md](./document-ia-api/docs/API_SUMMARY.md).

Stop local processes with `Ctrl+C` in the API and worker terminals, then:

```bash
docker compose down
```

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
| API setup, environment variables, initial admin API key (`DOCUMENT_IA_API_KEY`), run commands | [document-ia-api/README.md](./document-ia-api/README.md) |
| API architecture, routes, auth, error handling, workflow docs | [document-ia-api/docs/API_SUMMARY.md](./document-ia-api/docs/API_SUMMARY.md) |
| Database migration workflow | [document-ia-api/alembic/README.md](./document-ia-api/alembic/README.md) |
| Bruno API collection | [document-ia-api/bruno-api/README.md](./document-ia-api/bruno-api/README.md) |
| API test organization | [document-ia-api/tests/README.md](./document-ia-api/tests/README.md) |
| Worker execution flow, retries, DLQ, scheduler | [document-ia-worker/README.md](./document-ia-worker/README.md) |
| Shared infrastructure & `WEBHOOK_SECRET_ENCRYPTION_KEY` generation | [document-ia-infra/README.md](./document-ia-infra/README.md) |
| Redis Stream consumer (`BaseConsumer`, `ThreadConsumer`, `AsyncIoConsumer`) | [document-ia-infra/docs/REDIS_CONSUMER.md](./document-ia-infra/docs/REDIS_CONSUMER.md) |
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

If `init-s3-bucket` fails because MinIO is reported unhealthy, MinIO may still be running; retry bucket init only:

```bash
docker compose up --no-deps init-s3-bucket
```

### Local troubleshooting

| Symptom | What to check |
|---|---|
| `301` / `404` on `localhost:8000`, `Server: WSGIServer` | Another app is bound to port 8000: `lsof -nP -iTCP:8000 -sTCP:LISTEN` |
| `401` from Albert during OCR/LLM | `OPENAI_API_KEY` is not an Albert key, or `OPENAI_BASE_URL` is wrong |
| API key rejected after migration | `DOCUMENT_IA_API_KEY` does not match `APP_ENV` / pepper settings used at migration time |
| Tesseract OCR errors on macOS | Prefer Albert OCR via workflow override; if using `tesseract`, ensure `fra.traineddata` is a valid binary (not a bad download) |

## Common Tasks

Run the API:

```bash
cd document-ia-api
uv run python src/document_ia_api/main.py
```

Run the API with Uvicorn reload:

```bash
cd document-ia-api
uv run uvicorn src.document_ia_api.main:app --host 0.0.0.0 --port 8000 --reload
```

Run the worker:

```bash
cd document-ia-worker
uv run python src/document_ia_worker/main.py
```

Run the evaluation app:

```bash
cd document-ia-evals
uv run streamlit run src/document_ia_evals/app.py
```

Open the Bruno collection:

```bash
cd document-ia-api/bruno-api
bruno run workflows/execute.bru
```

Regenerate worker prompt snapshots after schema changes:

```bash
cd document-ia-worker
uv run python tests/fixtures/regenerate_extraction_prompt_fixtures.py
```

## Development

Each subproject owns its Python environment and dependency lock file. Install dependencies from the package you are working on:

```bash
cd document-ia-api
uv sync
```

```bash
cd document-ia-worker
uv sync
```

```bash
cd document-ia-schemas
uv sync
```

When developing against shared local packages, they are already configured in `pyproject.toml` and installed in editable mode by default when running `uv sync`.

### Git Hooks

The repository ships a [pre-commit](https://pre-commit.com/) configuration. Install the hooks once per clone:

```bash
pre-commit install
bash scripts/pre-push
```

Two hook types are installed:

- `pre-commit`: gitleaks scans staged changes.
- `pre-push`: a native wrapper scans the commits introduced by every pushed ref, including multi-ref pushes and secrets added then removed across intermediate commits.

The pre-push hook requires the `gitleaks` binary (v8.30.1) on your `PATH`; install it from the [gitleaks releases](https://github.com/gitleaks/gitleaks/releases). If it is missing, pushes are blocked. Run `bash scripts/pre-push` again after switching worktrees: Git hooks are local to each clone or worktree.

## Production & Deployment (Scalingo)

In production or during deployment on Scalingo, we want local path dependencies to be copied physically into the virtual environment instead of being symlinked (editable mode).

To achieve this, configure the `UV_NO_EDITABLE` environment variable in your Scalingo application settings:

```bash
scalingo env-set UV_NO_EDITABLE=1
```

When this variable is set, UV will automatically ignore the `editable = true` settings in `pyproject.toml` during the build process, ensuring all libraries are compiled and copied physically into the production container.

## Testing and Quality

Run tests from the relevant package:

```bash
cd document-ia-api
uv run pytest
uv run ruff check src tests
uv run pyright
```

```bash
cd document-ia-worker
uv run pytest
uv run ruff check src tests
```

```bash
cd document-ia-schemas
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## License

MIT. See [LICENSE](./LICENSE).
