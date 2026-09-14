# Document IA Worker

An asynchronous worker that executes document-processing workflows by consuming messages from a Redis Stream, orchestrating workflow Steps, and publishing events to the Event Store (PostgreSQL).

## Table of Contents
- Overview
- Execution Flow (from message to workflow completion)
- Workflow Context Between Steps
- Error Handling, Retry, and DLQ
- Redis Consumer (Multi-thread)
- Memory Optimization & OOM Protection (Scalingo / Linux Containers)
- Stress Testing & Load Validation (`scripts/stress_test_staging.py`)
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

## Memory Optimization & OOM Protection (Scalingo / Linux Containers)

In production and staging environments (e.g., Scalingo Linux containers with 2 GB RAM), workers process multi-page PDFs and heavy AI models (PyTorch, OpenCV, PyMuPDF, Tesseract, zxing). Without swap memory, exceeding physical RAM limits triggers immediate SIGKILL (`OOM Killed` / `Scalingo R14 Memory Exceeded`).

To guarantee stability and prevent OOM crashes under high concurrency (`REDIS_WORKER_NUMBER > 1`), the following optimizations are implemented:

### 1. `MALLOC_ARENA_MAX=2` (glibc Memory Fragmentation Control)
Native C/C++ libraries (PyTorch, OpenCV, PyMuPDF) allocate temporary memory arenas via glibc `malloc`. On multi-core host nodes, glibc defaults to creating up to `8 * num_cores` memory arenas, which prevents freed RAM from being returned to the OS.
- **Setting**: `export MALLOC_ARENA_MAX=2` (in `bin/start_worker.sh` and Scalingo environment variables).
- **Impact**: Reduces glibc memory fragmentation by up to 80%, forcing memory to be released back to the OS.

### 2. C/C++ CPU Thread Pool Limits
By default, PyTorch and OpenCV detect all host CPU cores (e.g. 16–32 cores) and spawn parallel OpenMP/MKL thread pools per model call, which inflates thread memory overhead.
- **Environment variables**:
  - `OMP_NUM_THREADS=1`
  - `MKL_NUM_THREADS=1`
  - `OPENBLAS_NUM_THREADS=1`
  - `OPENCV_FOR_THREADS_NUM=1`
- **Runtime initialization**: `main.py` explicitly invokes `torch.set_num_threads(1)` and `cv2.setNumThreads(1)` at startup.

### 3. AI Model Pre-bundling & Boot Pre-warming
- **Pre-downloading at build time**: Model weights for **YOLO-World** (`yolov8m-world.pt`) and **QRDet** (`qrdet-s.pt`), as well as Tesseract language files (`fra.traineddata`), are downloaded during `bin/post_compile` and stored in `$APP_ROOT/.models/`.
- **Pre-warming on boot**: Before listening to Redis events, `src/document_ia_worker/main.py` invokes `_prewarm_models()` to load YOLO-World and QRDet models into RAM once at worker startup. This avoids concurrent on-the-fly downloads, model reloading delays, or race conditions during job execution.

### 4. Critical Section Thread Locking for Heavy C/RAM Steps
Network I/O steps (downloading from S3, HTTP OCR, LLM API calls) use virtually zero RAM and run with high concurrency (`REDIS_WORKER_NUMBER = 10+`).
However, local PDF rasterization and PyTorch inference are heavy in RAM. Thread locks serialize only these brief C/RAM intensive phases:
- `_PDF_LOCK` in `PreprocessFileStep` (PyMuPDF PDF page rendering)
- `_YOLO_LOCK` in `yoloworld_crop.py` (YOLO-World object detection)
- `_QRDET_LOCK` in `extract_barcode_2ddoc_data.py` (QRDet barcode detection)

This allows high Redis concurrency (`REDIS_WORKER_NUMBER = 10`) for I/O bound waiting while keeping peak RAM footprint under 1.5 GB.

---

## Stress Testing & Load Validation (`scripts/stress_test_staging.py`)

A load testing script is available at `scripts/stress_test_staging.py` to validate worker memory stability and throughput under concurrent requests.

### Features
- Sends $N$ concurrent HTTP POST requests with `multipart/form-data` payload and Tesseract OCR override.
- Extracts `execution_id` from the API response (`data.execution_id`).
- Asynchronously polls `GET /api/v1/executions/{execution_id}` with staggered polling intervals (default: `2.5s`) to avoid API rate limiting / 502 proxy errors.
- Automatically handles temporary 502/503 HTTP gateway errors during polling.
- Enforces a per-request timeout (default: 60 seconds). If an execution does not complete within 60s, it is marked as `TIMEOUT`.
- Computes global end-to-end duration and per-request min/max/average processing times.

### Script Usage & Options

```bash
# Basic usage (--file is required, --api-key is required)
uv run python scripts/stress_test_staging.py \
  --api-key "YOUR_STAGING_API_KEY" \
  --file "/path/to/your/document.pdf" \
  -c 10 \
  -n 10
```

#### CLI Parameters:
| Option | Description | Default |
| :--- | :--- | :--- |
| `--api-key` | *(Required)* API key (`X-Api-Key` header) | - |
| `--file` | *(Required)* Path to local PDF document | - |
| `--url` | Workflow execution URL v2 | `https://api.staging.document-ia.beta.gouv.fr/...` |
| `-c`, `--concurrency` | Number of parallel concurrent requests | `10` |
| `-n`, `--total-requests` | Total number of requests to execute | `10` |
| `--poll-interval` | Interval in seconds between polling attempts | `2.5` |
| `--max-timeout` | Maximum wait time in seconds before timing out an execution | `60.0` |

#### Example: Stress test with 20 requests and custom timeout
```bash
uv run python scripts/stress_test_staging.py \
  --api-key "YOUR_STAGING_API_KEY" \
  --file "/Users/user/Documents/test_avis.pdf" \
  -c 20 \
  -n 20 \
  --poll-interval 3.0 \
  --max-timeout 60
```

---

## Configuration & Running
Prerequisites:
- PostgreSQL, Redis, S3/MinIO (same services as the API). See the root `docker-compose.yml`.

Install (UV):
```bash
# In document-ia-worker/
uv sync
```

Run the worker:
```bash
cd document-ia-worker
uv run python src/document_ia_worker/main.py
```

---

## Tests & Prompt Snapshots

The extraction prompts produced by `PromptService` are covered by **snapshot tests**. For each supported document type, the rendered extraction prompt is stored as a reference file and compared against the freshly rendered prompt during the test run.

Key paths:
- `tests/snapshots/prompts/extraction/<document_type>.txt` — reference prompts (one file per document type, e.g. `devis_pac.txt`).
- `tests/unit/test_prompt_service.py` — the test that re-renders each prompt and asserts it matches the snapshot.
- `tests/fixtures/regenerate_extraction_prompt_fixtures.py` — the script that (re)generates every snapshot.

Run the snapshot tests:
```bash
cd document-ia-worker
uv run pytest tests/unit/test_prompt_service.py -q
```

### Regenerating snapshots

When a schema in `document-ia-schemas` changes (new field, renamed field, edited description or example), the rendered prompt changes too and the snapshot test will fail until the reference files are regenerated:

```bash
cd document-ia-worker
uv run python tests/fixtures/regenerate_extraction_prompt_fixtures.py
```

This rewrites **all** snapshots under `tests/snapshots/prompts/extraction/`. Review the `git diff` and commit only the intended changes.

---

## Environment Variables

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
- `LOKI_BEARER_TOKEN` (secret, default: `None`)

When Loki push requires authentication, set `LOKI_BEARER_TOKEN` to the raw token (without the `Bearer ` prefix). The handler sends `Authorization: Bearer <token>` on each request to `/loki/api/v1/push`. Leave it empty to keep unauthenticated push.

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

Scheduled tasks are declared in the `cron.json` file at the root of the worker project. The runtime format is a `jobs` array where each entry specifies:

- the **cron expression + command** in `command` (for example `0 5 * * * python -u ...`),
- the scheduler **size hint** in `size`.

Current jobs:

```json
{
  "jobs": [
    {
      "command": "0 3 * * * python -u src/document_ia_task_scheduler/task/remove_ppi/main.py",
      "size": "S"
    },
    {
      "command": "0 5 * * * python -u src/document_ia_task_scheduler/task/replicate_analytics/main.py",
      "size": "L"
    }
  ]
}
```

### Task code location and entrypoints

Task entrypoints are Python scripts under:

```text
src/document_ia_task_scheduler/task/<task_name>/main.py
```

Examples:
- `src/document_ia_task_scheduler/task/remove_ppi/main.py`
- `src/document_ia_task_scheduler/task/replicate_analytics/main.py`

### ReplicateAnalytics (daily 05:00)

Purpose:
- replicate reference data (`organization`) from the main DB to the analytics DB,
- replicate `event_store` incrementally with payload anonymization.

Behavior:
- `organization`: full replication with per-row upsert (small reference table, up to ~1000 rows).
- `event_store`: incremental replication using destination cursor `MAX(created_at)` and source filter `created_at >= cursor`.
- deduplication at insert-time with `INSERT ... ON CONFLICT (id) DO NOTHING`.
- anonymization on copied events only (source entities are not mutated):
  - `WorkflowExecutionStarted`: clear `file_info` and `metadata`,
  - `WorkflowExecutionStepCompleted`: clear `final_result`.

Idempotency and loop completion:
- re-reading the boundary timestamp is expected and safe (`ON CONFLICT` drops duplicates),
- loop stops on incomplete batch (`len(events) < ANALYTICS_EVENT_BATCH_SIZE`),
- cursor advances to the last fetched `created_at`.

Environment variables:
- Analytics DB connection (optional, shared settings):
  - `ANALYTICS_POSTGRESQL_URL`
  - or `ANALYTICS_POSTGRES_HOST`, `ANALYTICS_POSTGRES_PORT`, `ANALYTICS_POSTGRES_DB`, `ANALYTICS_POSTGRES_USER`, `ANALYTICS_POSTGRES_PASSWORD`, `ANALYTICS_POSTGRES_SSL_MODE`
- Task tuning:
  - `ANALYTICS_EVENT_BATCH_SIZE` (default: `5000`)

### PaaS rollout (Heroku / Coolify / Scalingo)

Recommended rollout checklist:
- Provision a dedicated analytics PostgreSQL database.
- Set `ANALYTICS_*` variables on both API and worker apps.
- Configure the `UV_NO_EDITABLE=1` environment variable to ensure local dependencies are installed in non-editable mode.
- Ensure the scheduler process is enabled for `cron.json` jobs.
- Start/restart API first so analytics migrations are applied.
- Confirm worker logs show `ReplicateAnalytics` execution and replicated counts.

Important:
- Analytics schema is managed by API Alembic startup migration.
- Without `ANALYTICS_*`, analytics migration is skipped and replication must not be enabled.

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
