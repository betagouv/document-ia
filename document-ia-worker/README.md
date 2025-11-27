# Document IA Worker

An asynchronous worker that executes document-processing workflows by consuming messages from a Redis Stream, orchestrating workflow Steps, and publishing events to the Event Store (PostgreSQL).

## Table of Contents
- Overview
- Execution Flow (from message to workflow completion)
- Workflow Context Between Steps
- Error Handling, Retry, and DLQ
- Redis Consumer (Multi-thread)
- Configuration & Running
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


## Env Variables

## Marker configuration
- `MARKER_API_KEY` (secret, default: `None`) — API key for Marker service.
- `MARKER_BASE_URL` (str, default: `None`) — Base URL for Marker API.

### Redis
- `REDIS_HOST` (str, défaut : `"localhost"`) — hôte Redis.
- `REDIS_PORT` (int, défaut : `6379`) — port Redis.
- `REDIS_DB` (int, défaut : `0`) — index de base de données Redis.
- `REDIS_PASSWORD` (secret, défaut : `"password"`) — mot de passe Redis.
- `REDIS_WORKER_NUMBER` (int, défaut : `1`) — nombre de workers Redis (pour les consumers côté infra).
- `REDIS_URL` (str, défaut : `None`) — URL de connexion Redis complète (si fournie, peut remplacer host/port/db).
- `EVENT_STREAM_NAME` (str, défaut : `"event_stream"`) — nom du stream Redis pour les évènements.
- `EVENT_STREAM_EXPIRATION` (int, défaut : `300`) — TTL (en secondes) des entrées du stream.
- `EVENT_STREAM_MAXLEN` (int, défaut : `1000`) — taille max du stream avant trimming.
- `EVENT_CONSUMER_GROUP` (str, défaut : `"workflow_execution_consumer"`) — nom du consumer group Redis.

### S3 / MinIO
- `S3_ENDPOINT_URL` (str, défaut : `"http://localhost:9000"`) — endpoint S3/MinIO.
- `S3_ACCESS_KEY_ID` (secret, défaut : `"minioadmin"`) — access key S3/MinIO.
- `S3_SECRET_ACCESS_KEY` (secret, défaut : `"minioadmin"`) — secret key S3/MinIO.
- `S3_BUCKET_NAME` (str, défaut : `"document-ia"`) — nom du bucket par défaut.
- `S3_REGION_NAME` (str, défaut : `"us-east-1"`) — région S3 (placeholder pour MinIO).
- `S3_USE_SSL` (bool, défaut : `False`) — active HTTPS vers S3/MinIO.

### Base de Données PostgreSQL
- `POSTGRES_DB` (str, défaut : `None`) — nom de la base.
- `POSTGRES_HOST` (str, défaut : `None`) — hôte PostgreSQL.
- `POSTGRES_PORT` (int, défaut : `5432`) — port PostgreSQL.
- `POSTGRES_SSL_MODE` (str, défaut : `None`) — mode SSL (`disable`, `require`, etc.).
- `POSTGRES_USER` (str, défaut : `None`) — utilisateur DB.
- `POSTGRES_PASSWORD` (secret, défaut : `None`) — mot de passe DB.
- `POSTGRESQL_URL` (str, défaut : `None`) — URL de connexion complète (si fournie, prioritaire).

### Logging & Loki
- `LOKI_URL` (str, défaut : `""`) — URL de l’instance Loki.
- `LOKI_LOGGING_ENABLED` (bool, défaut : `True`) — active/désactive l’envoi des logs vers Loki.

### OpenAI / LLM
- `OPENAI_API_KEY` (secret, défaut : `None`) — clé API OpenAI.
- `OPENAI_BASE_URL` (str, défaut : `None`) — endpoint OpenAI custom (par ex. proxy).
- `OPENAI_ENCODING_MODEL` (str, défaut : `"gpt-4"`) — modèle utilisé pour le comptage de tokens.
- `OPENAI_TIMEOUT` (int, défaut : `30`) — timeout (en secondes) des requêtes OpenAI.
- `OPENAI_MAX_RETRIES` (int, défaut : `3`) — nombre max de retries pour les appels OpenAI.


Local dependency `document-ia-infra`:
- The worker depends on `document-ia-infra` (installed in editable mode). Changes in `document-ia-infra/src` become visible after restarting the worker process.

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
