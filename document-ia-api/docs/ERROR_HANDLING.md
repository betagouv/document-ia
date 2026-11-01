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
| `503` | execution could not be scheduled (see below) |

## Execution scheduling failures

An execution is only reported as accepted (`processing`) once its processing has
actually been scheduled on the Redis stream. If the publication fails, both v1
and v2 execution endpoints return `503` with a bounded `Retry-After` header
(configured by `PUBLISH_RETRY_AFTER_SECONDS`, default 5 seconds):

```json
{
  "type": "about:blank",
  "title": "Service Unavailable",
  "status": 503,
  "code": "http.error",
  "errors": {
    "error": "execution_scheduling_unavailable",
    "execution_id": "exec_123",
    "message": "The execution could not be scheduled. No processing is pending; retry the request."
  }
}
```

The started event is kept as the record of the request, and a terminal failure
event closes the execution: reading that execution returns `FAILED` instead of a
`STARTED` that would never progress. The closure keeps the workflow version of
the started event, so v2 executions stay readable. An uploaded file is likewise
kept; storage, PostgreSQL and Redis are deliberately not made atomic here.

If writing that failure event itself fails, the error is logged and the `503` is
still returned: the response remains the contract, but such an execution can stay
`STARTED` until it is reconciled. Separately, Redis `maxlen` truncation is not a
saturation error — the write is accepted and the oldest entries are dropped — so
stream-capacity admission control is not covered by this behaviour.

Retrying the request creates a new execution with a new `execution_id`. Because
the failed attempt scheduled no work, no execution is left processing the same
document twice. There is no `Idempotency-Key` support: a client that loses a
successful response cannot retrieve the original execution by key.

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
