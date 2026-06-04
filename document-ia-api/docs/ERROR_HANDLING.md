# Error Handling

## Response format

The API standardizes errors using a Problem Details-like format, for example:

```json
{
  "type": "about:blank",
  "title": "Bad Request",
  "status": 400,
  "code": "http.validation_error",
  "detail": "Explicit message",
  "instance": "/api/v2/workflows/{workflow_id}/execute",
  "errors": {}
}
```

## Common status codes

| Code | Typical cases |
|---|---|
| `400` | invalid payload, invalid override, invalid `file` / `file_url` combination |
| `401` | authentication failed (missing API key, invalid API key) |
| `403` | authenticated but not authorized (admin role required, foreign resource access) |
| `404` | missing entity (workflow, execution, organization, webhook...) |
| `408` | `execute-sync` timeout |
| `422` | schema/request validation errors |
| `429` | rate limit exceeded |
| `500` | unhandled internal error |

## Sync workflow timeout errors

For `execute-sync`, on timeout:

```json
{
  "type": "about:blank",
  "title": "Request Timeout",
  "status": 408,
  "code": "workflow.timeout",
  "detail": "Workflow execution did not finish before timeout",
  "errors": {
    "error": "sync_execution_timeout",
    "execution_id": "exec_123",
    "last_status": "STARTED"
  }
}
```

## Design principles

- explicit business errors (missing entities, invalid override),
- known HTTP errors are propagated,
- DB rollback on execution-route failures,
- structured logs for server-side diagnostics.
