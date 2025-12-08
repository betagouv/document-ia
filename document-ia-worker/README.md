# Document IA Worker

An asynchronous worker that executes document-processing workflows by consuming messages from a Redis Stream, orchestrating workflow Steps, and publishing events to the Event Store (PostgreSQL).

## Table of Contents
- Overview
- Execution Flow (from message to workflow completion)
- Workflow Context Between Steps
- Error Handling, Retry, and DLQ
- Redis Consumer (Multi-thread)
- Configuration & Running
- Environment Variables
- Scheduled Tasks (Task Scheduler)
- Best Practices & Troubleshooting

---

## Overview
The worker listens to a Redis stream for “workflow execution” messages. Upon receiving a message:
1) `WorkflowManager` loads the initial event (WorkflowExecutionStarted) from the Event Store and resolves the workflow definition.
2) It builds a chain of Steps (Download → Preprocess → OCR → LLM → Save) and executes each step sequentially.
3) Each Step reads/writes into a shared context and may publish events (success/failure) via the Event Store.
4) Errors are categorized as “retryable” or “non‑retryable”; the consumer handles retry, DLQ, and pending message reclaim.

Key paths:
- `src/document_ia_worker/workflow/workflow_manager.py` — orchestrates the workflow.
- `src/document_ia_worker/workflow/step/*` — workflow Steps (download, preprocess, ocr, llm, save...).
- `document-ia-infra/src/document_ia_infra/redis/consumer.py` — generic Redis consumer (shared infra code).
- `document-ia-infra/src/document_ia_infra/service/event_store_service.py` — event publishing.

---

## Execution Flow
1) The consumer reads a batch of messages with `XREADGROUP` on the configured stream.
2) Each message is decoded into a type `T` (implementing `SerializableMessage`).
3) Message processing is submitted to a `ThreadPoolExecutor`. Each thread creates its own asyncio event loop and runs the async coroutine `process_message_callable(message, retry_count)`.
4) `WorkflowManager`:
   - Retrieves a “created” event that is not closed (i.e., not Completed/Failed non‑retryable) using `EventRepository.get_created_event_if_execution_not_completed_or_failed`.
   - Loads the workflow definition (steps).
   - Executes each Step, aggregates results in a shared context, and publishes final events.
5) When done (or if an error occurs), the consumer ACKs the message (`XACK`), or performs retry / DLQ according to the failure type.

---

## Workflow Context Between Steps
Two levels of context are used:

1) Main context: `MainWorkflowContext`
   - Passed by reference to Steps at construction (e.g., temp paths, counters, start timestamps, etc.).
   - Holds transversal state that is not serialized.

2) Results context: `workflow_context: dict[str, Any]`
   - Shared by `WorkflowManager` across Steps.
   - For each Step:
     - `step.inject_workflow_context(workflow_context)` grants access to previously produced results.
     - After `await step.execute()`, the result is stored under a normalized key: `workflow_context[step.get_context_result_key()] = result`.

Best practices:
- Derive the key via `get_context_result_key()` to avoid collisions.
- Use Pydantic models for exchanged data (validation), and only serialize at boundaries (DB/S3/Redis).
- Implement `cleanup()` in each Step to release resources (temporary files, handles). `WorkflowManager` calls cleanup in LIFO order.

---

## Error Handling, Retry, and DLQ
Step failures are normalized as:
- Internal helper methods of `WorkflowManager` wrap errors into `WorkflowStepException(step_name, inner_exception)` to preserve both the failing step and the original exception.
- A `RetryableException` (infra) marks a transient/temporary failure that should be retried.

On failure:
- `_save_failure_event` publishes a `WorkflowExecutionFailed` event via `EventStoreService.emit_workflow_failed` with:
  - `error_type` = `RetryableException` if the inner exception is retryable, else the exception class name.
  - `error_message` = message of the (inner) exception.
  - `failed_step` = the name of the failing step.
  - `retry_count` = how many attempts were already made for this message.

On the consumer side (`infra/redis/consumer.py`):
- If processing raises `RetryableException`, the message is re‑queued on the stream with `retries = retries + 1` while `retries < max_retry_number`.
- If a non‑retryable error occurs, the message is sent to the DLQ stream.
- If re‑queuing itself fails, the message is sent to the DLQ stream.
- The DLQ stream is named `"<stream>:dlq"` and stores fields such as: `data`, `retries`, `original_id`, `reason`, `error`, `consumer`, `timestamp`.

Reclaiming pending messages:
- A background “reclaimer” task uses `XAUTOCLAIM` to recover idle messages (idle > RECLAIM_IDLE_MS), increments `retries`, and attempts to re‑queue them; if retry limits are exceeded, the message is routed to DLQ.

ACKs/NACKs:
- All code paths (success, non‑retryable error, DLQ) eventually `XACK` the original message to avoid infinite loops.

---

## Redis Consumer (Multi‑thread)
The consumer uses a `ThreadPoolExecutor` to process each message in a dedicated thread, creating an **asyncio event loop per thread** to run `process_message_callable(message, retry_count)`.

Key points:
- Async resources (async Redis client, async DB sessions) are **bound to the event loop** that created them. Do not use a client/session created on the main loop from a worker thread loop.
- If a Step needs async I/O in the thread, create these resources inside that thread (or marshal the I/O back to the main loop if needed).
- For CPU‑bound tasks (OCR, heavy parsing), threads work well. For external binaries (e.g., Tesseract), consider `asyncio.create_subprocess_exec` to run subprocesses concurrently without blocking the loop.

Concurrency knobs:
- `worker_number`: thread pool size (per message). Start with 1 in debug.
- `batch_size`, `block_time`: batching and blocking timeout for `XREADGROUP`.
- `max_retry_number`: retry limit before DLQ.

---

## Configuration & Running
Prerequisites:
- PostgreSQL, Redis, S3/MinIO (same services as the API). See the root `docker-compose.yml`.

Install (Poetry):
```bash
# In document-ia-worker/
poetry install
```

Run the worker:
```bash
cd document-ia-worker
poetry run python src/document_ia_worker/main.py
```


## Environment Variables

### Marker configuration
- `MARKER_API_KEY` (secret, default: `None`) — API key for Marker service.
- `MARKER_BASE_URL` (str, default: `None`) — Base URL for Marker API.

### Redis
- `REDIS_HOST` (str, default: `"localhost"`)
- `REDIS_PORT` (int, default: `6379`)
- `REDIS_DB` (int, default: `0`)
- `REDIS_PASSWORD` (secret, default: `"password"`)
- `REDIS_WORKER_NUMBER` (int, default: `1`)
- `REDIS_URL` (str, default: `None`)
- `EVENT_STREAM_NAME` (str, default: `"event_stream"`)
- `EVENT_STREAM_EXPIRATION` (int, default: `300`)
- `EVENT_STREAM_MAXLEN` (int, default: `1000`)
- `EVENT_CONSUMER_GROUP` (str, default: `"workflow_execution_consumer"`)

### S3 / MinIO
- `S3_ENDPOINT_URL` (str, default: `"http://localhost:9000"`)
- `S3_ACCESS_KEY_ID` (secret, default: `"minioadmin"`)
- `S3_SECRET_ACCESS_KEY` (secret, default: `"minioadmin"`)
- `S3_BUCKET_NAME` (str, default: `"document-ia"`)
- `S3_REGION_NAME` (str, default: `"us-east-1"`)
- `S3_USE_SSL` (bool, default: `False`)

### PostgreSQL
- `POSTGRES_DB` (str, default: `None`)
- `POSTGRES_HOST` (str, default: `None`)
- `POSTGRES_PORT` (int, default: `5432`)
- `POSTGRES_SSL_MODE` (str, default: `None`)
- `POSTGRES_USER` (str, default: `None`)
- `POSTGRES_PASSWORD` (secret, default: `None`)
- `POSTGRESQL_URL` (str, default: `None`)

### Logging & Loki
- `LOKI_URL` (str, default: `""`)
- `LOKI_LOGGING_ENABLED` (bool, default: `True`)

### OpenAI / LLM
- `OPENAI_API_KEY` (secret, default: `None`)
- `OPENAI_BASE_URL` (str, default: `None`)
- `OPENAI_ENCODING_MODEL` (str, default: `"gpt-4"`)
- `OPENAI_TIMEOUT` (int, default: `30`)
- `OPENAI_MAX_RETRIES` (int, default: `3`)

### Task Scheduler
- `EVENT_STORE_PPI_RETENTION_DAYS` (int, default: `7`)

Local dependency `document-ia-infra`:
- The worker depends on `document-ia-infra` (installed in editable mode). Changes in `document-ia-infra/src` become visible after restarting the worker process.

---

## Scheduled Tasks (Task Scheduler)

The worker also ships with a lightweight task scheduler used to run recurring jobs (maintenance, anonymization, cleanup, etc.).

### Task definition: `cron.json`

Scheduled tasks are declared in the `cron.json` file at the root of the worker project. Each entry typically specifies:

- the **task name** (`task_name`),
- the **schedule** (cron-like expression or interval, depending on your implementation),
- optional **parameters** or flags (for example, `enabled`).

Example (illustrative only):

```json
[
  {
    "task_name": "anonymize_events",
    "schedule": "0 * * * *",
    "enabled": true
  }
]
```

### Task code location

For each `task_name` defined in `cron.json`, the corresponding implementation lives under:

```text
src/document_ia_task_scheduler/task/<task_name>/main.py
```

By convention:
- `<task_name>` must match exactly the `task_name` value from `cron.json`.
- The `main.py` module exposes the entry point for the task (for example, `async def run()` or `def main()`), which contains the actual job logic.

Example: for a task named `anonymize_events` in `cron.json`, the code would be located at:

```text
src/document_ia_task_scheduler/task/anonymize_events/main.py
```

The scheduler uses this convention to resolve and execute the appropriate task module at runtime.

---

## Best Practices & Troubleshooting
- “Future attached to a different loop”: indicates you used an async resource created on the main loop inside a thread (different loop). Create the resource in the thread or run the I/O on the original loop.
- DLQ: monitor `"<stream>:dlq"` and inspect `reason` (`decode_error`, `not_retryable_error`, `max_retries_exceeded`, `error_requeueing_message`).
- Context: prefer Pydantic models for data exchanges between Steps; always free resources in `cleanup()`.
- Idempotency: for DB/S3 writes, prefer idempotency keys or stable IDs to avoid duplicates under retry.
- Logging: include consumer and message IDs; add thread names if useful for multi‑thread debugging.

---

## License
MIT (or according to your LICENSE file)
