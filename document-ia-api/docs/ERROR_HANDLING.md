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
| `409` | idempotency conflict or concurrent request in progress |
| `422` | schema/request validation errors |
| `429` | rate limit exceeded |
| `500` | unhandled internal error |
| `503` | execution capacity unavailable (saturation) or publication failed (see below) |

## Execution admission control (Saturation & Backpressure)

Before accepting a new execution (and before uploading files to S3 or creating start events in PostgreSQL), the API checks stream admission capacity across both worker execution and webhook notification streams.

If the queue is saturated, or if the oldest unacknowledged message exceeds the maximum age, the API returns `503` with a `Retry-After` header (configured by `PUBLISH_RETRY_AFTER_SECONDS`, default 5 seconds):

```json
{
  "type": "about:blank",
  "title": "Service Unavailable",
  "status": 503,
  "code": "http.service_unavailable",
  "errors": {
    "error": "execution_capacity_unavailable",
    "message": "Execution capacity is unavailable. Retry the request later."
  }
}
```

Admission thresholds use hysteresis to avoid oscillation (flapping):
- `ADMISSION_MAX_OUTSTANDING` (default 1000): stops admission when `lag + pending` entries across the stream reach this count.
- `ADMISSION_RESUME_OUTSTANDING` (default 800): reopens admission only once outstanding entries drop to or below this threshold.
- `ADMISSION_MAX_AGE_SECONDS` (default 300s): stops admission when the oldest unacknowledged entry (`PEL` or unread) in either stream exceeds this age, protecting against hung/stalled workers or extreme processing delays.
- `ADMISSION_RESUME_AGE_SECONDS` (default 120s): reopens admission only once the oldest entry age drops to or below this threshold.
- `ADMISSION_MAX_RETAINED` (default 10000): stops admission when total entries in Redis (`XLEN(stream) + XLEN(stream:dlq)`) reach this ceiling, protecting Redis memory if completed entries or DLQ entries accumulate.
- `ADMISSION_RESUME_RETAINED` (default 8000): reopens admission once maintenance cleanup drains retained entries back down to this threshold.

Quota check failures (e.g., Redis outage during rate limiting) also fail closed and return `503 execution_capacity_unavailable`. Result read endpoints (`GET /api/v1/executions/{id}`) are not admission-gated and remain readable even when Redis is down.

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
document twice. When an `Idempotency-Key` was provided, the key is immediately
released upon scheduling failure so that the retry can proceed without waiting
for the lock to expire.

## Idempotency-Key support and resilience

To protect against network drops, client disconnections, or gateway timeouts, the asynchronous workflow execution endpoints (`POST /api/v2/workflows/{id}/execute` and `POST /api/v1/workflows/{id}/execute`) support the optional `Idempotency-Key` request header (following the IETF standard draft).

The synchronous route (`execute-sync`) is exclusively intended for interactive debugging and does not support idempotency keys.

### Key requirements & validation
- Format: printable ASCII string (characters 32 to 126 inclusive).
- Length: between 1 and 256 characters inclusive.
- Invalid keys are immediately rejected with `400 Bad Request` (`error: invalid_idempotency_key`).

### Request fingerprinting
A SHA-256 fingerprint is computed combining the HTTP method, canonical path, canonicalized JSON parameters (`metadata`, `override`, `classification-parameters`, `extraction-parameters`), and document:
- For `UploadFile`: streamed in 64KB chunks to hash contents, resetting the cursor (`await file.seek(0)`) so the downstream upload to S3 is unaffected.
- For `file_url`: hashed from the normalized URL.

### Four execution outcomes
1. **First submission (Miss)**: An atomic Lua script sets the key in Redis with status `IN_PROGRESS` and a 60-second safety lock TTL (`IDEMPOTENCY_LOCK_TTL_SECONDS`). The execution is scheduled; upon success, the key transitions to `COMPLETED` with retention TTL (default 12 hours / 43,200 seconds via `IDEMPOTENCY_KEY_TTL_SECONDS`).
2. **Replay after lost response (Hit COMPLETED with same fingerprint)**: The API reconstructs the original acceptance response directly from the EventStore with the same `execution_id` and adds the HTTP response header `Idempotent-Replay: true`. No new DB events, S3 uploads, or Redis messages are generated.
3. **Payload conflict (Hit with different fingerprint)**: Reusing the same key with different documents or parameters returns `409 Conflict`:
```json
{
  "type": "about:blank",
  "title": "Conflict",
  "status": 409,
  "code": "http.conflict",
  "errors": {
    "error": "idempotency_conflict",
    "message": "The idempotency key is already used with a different request payload."
  }
}
```
4. **Concurrent request in flight (Hit IN_PROGRESS)**: If a duplicate arrives while the first is being processed, the server does not block or hold connections. It responds immediately with `409 Conflict` containing the pre-reserved `execution_id`:
```json
{
  "type": "about:blank",
  "title": "Conflict",
  "status": 409,
  "code": "http.conflict",
  "errors": {
    "error": "idempotency_in_progress",
    "execution_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "message": "An execution with this idempotency key is currently being processed. You can query its status using the provided execution_id."
  }
}
```

### Scheduling failure cleanup
If scheduling on Redis streams fails (`PublishFailedError` / `503 Service Unavailable`), the key is immediately released in Redis so the client can retry immediately without waiting for the 60s lock timeout.

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
