# Architecture

## Overview

The API exposes FastAPI endpoints to:

- start workflow executions (v1 and v2),
- retrieve execution status,
- manage organizations/API keys/webhooks.

Document processing itself is executed asynchronously by the worker.

## Main execution flow

1. API validates the request.
2. API stores a `WORKFLOW_EXECUTION_STARTED` event in DB.
3. API publishes a Redis message (`workflow_execution_id`).
4. Worker consumes the message, executes steps, and emits progress/final events.
5. API reads the Event Store to expose final status through `/executions` (or `execute-sync`).

## Components

- **FastAPI app**: `src/document_ia_api/main.py`
- **Routes**: `src/document_ia_api/api/routes`
- **Application services**:
  - `WorkflowService` (v1),
  - `WorkflowV2Service` (v2),
  - `ExecutionService` (Event Store -> API contract mapping)
- **Infra**:
  - PostgreSQL (Event Store + admin entities),
  - Redis (rate limiting + messaging),
  - S3/MinIO (file storage),
  - Alembic (migrations).

## Workflow versioning

- **v1**: static JSON definition, legacy endpoint.
- **v2**: YAML definition, step-level overrides (`override`), resolved configuration stored in the started event.

## Observability

- structured logs (middlewares + services),
- documentation endpoints `/docs` and `/redoc`,
- error handling with Problem Details-like format.
