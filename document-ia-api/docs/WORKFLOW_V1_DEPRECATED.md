# Workflow v1 (Deprecated)

> v1 is kept for compatibility. For any new integration, use v2.

## v1 workflow endpoints

- `POST /api/v1/workflows/{workflow_id}/execute`
- `POST /api/v1/workflows/{workflow_id}/execute-sync`
- `GET /api/v1/executions/{execution_id}`

## Payload

`execute` and `execute-sync` accept a multipart form:

- `file` (binary) **or**
- `file_url` (string),
- `metadata` (JSON string),
- (v1 only) `classification-parameters`,
- (v1 only) `extraction-parameters`.

## Behavior

1. input validation,
2. optional S3 file upload,
3. v1 started event emission,
4. Redis publication,
5. status tracking through `/executions/{execution_id}`.

## Why deprecated

- less flexible step configuration,
- less expressive config model than v2,
- no step-level override mechanism equivalent to v2.

## Migration tips v1 -> v2

1. Identify the target v2 workflow with `GET /api/v2/workflows/`.
2. Move v1 parameters to `override`.
3. Switch calls to:
   - `POST /api/v2/workflows/{workflow_id}/execute`, or
   - `POST /api/v2/workflows/{workflow_id}/execute-sync`.
