# Event Data Minimization and Retention Architecture

## Overview

Document IA implements strict data minimization and privacy compliance (GDPR / F11) across its event sourcing infrastructure (`event_store`) and analytics replication. Sensitive artifacts—such as raw file download URLs, temporary S3 object paths, intermediate OCR extractions, final document payloads, and runtime error details—must be purged after a defined retention window (default: 7 days).

This document details the architectural boundaries, payload minimization rules across all four persisted event types, the background purge scheduler (`RemovePPI`), idempotent analytics replication (`ReplicateAnalytics`), and the API contract for reading purged executions.

---

## Architecture Diagram

```mermaid
flowchart TD
    subgraph "Operational Database (Main DB)"
        ES_PENDING["event_store (anonymization_status = 'PENDING')"]
        ES_ERROR["event_store (anonymization_status = 'ERROR')"]
        ES_DONE["event_store (anonymization_status = 'DONE')"]
    end

    subgraph "Worker - Scheduled Tasks"
        RPPI["RemovePPI Job<br/>(Daily at 03:00 UTC)<br/>Batch size: 1000 (while True)"]
        REPL["ReplicateAnalytics Job<br/>(Daily at 05:00 UTC)<br/>Incremental with UPSERT"]
    end

    subgraph "Analytics Database (Destination DB)"
        A_ES["event_store<br/>(Synchronized & Minimized)"]
    end

    subgraph "Client Read APIs"
        API_GET["GET /api/v1/executions/{id}<br/>(ExecutionService)"]
        CLIENT["API Client / Webhook Consumer<br/>(purged = true)"]
    end

    ES_PENDING -->|Cutoff: 7 days| RPPI
    ES_ERROR -->|Automatic retry| RPPI
    RPPI -->|In-place payload cleanup| ES_DONE

    ES_PENDING -->|Incremental read| REPL
    ES_DONE -->|Incremental read| REPL
    REPL -->|ON CONFLICT (id) DO UPDATE| A_ES

    ES_DONE --> API_GET
    API_GET --> CLIENT
```

---

## 1. Event Payload Minimization Rules

The event store records four immutable workflow event types. During the purge process (`EventRepository.anonymize_payload`), payloads are mutated in place to strip all sensitive markers:

| Event Type | Preserved Operational Metadata | Purged Sensitive Data | Purge Mutation |
|---|---|---|---|
| `WorkflowExecutionStartedEvent` | `workflow_id`, `execution_id`, `organization_id`, `created_at`, `version`, `classification_parameters`, `extraction_parameters`, `workflow_configuration` | `s3_file_info`, `file_url`, `metadata` | `s3_file_info = None`<br>`file_url = None`<br>`metadata = {}` |
| `WorkflowExecutionStepCompletedEvent` | `step_name`, `execution_time_ms` | `step_result` (raw OCR text, LLM chunks), `output_data` | `step_result = {}`<br>`output_data = None` |
| `WorkflowExecutionCompletedEvent` | `total_processing_time_ms`, `steps_completed` | `final_result` (extracted personal data, classification explanation, 2D-Doc/barcode contents), `output_summary`, `workflow_metadata` | `final_result = {}`<br>`output_summary = {}`<br>`workflow_metadata = None` |
| `WorkflowExecutionFailedEvent` | `error_type`, `failed_step`, `retry_count` | `error_message` (stack traces with payload or presigned URL excerpts) | `error_message = "[PURGED]"` |

> [!IMPORTANT]
> In `WorkflowExecutionStartedEvent`, `s3_file_info` must be set to `None` rather than `{}`. Because `FileInfo` defines required fields (`filename`, `s3_key`, `size`), passing an empty dictionary causes Pydantic schema validation failures upon subsequent reads. Setting `None` conforms to `Optional[FileInfo]`.

---

## 2. Worker Purge Scheduler (`RemovePPI`)

The `RemovePPI` job runs nightly as a background scheduled task. It includes the following resilience mechanisms:

1. **Chunked Keyset Batching**:
   Events are queried in batches of 1000 (`batch_size = 1000`) in a `while True` loop until all records older than `EVENT_STORE_PPI_RETENTION_DAYS` (7 days) are processed:
   ```sql
   SELECT * FROM event_store
   WHERE created_at <= :before_date
     AND anonymization_status IN ('PENDING', 'ERROR')
   ORDER BY created_at ASC
   LIMIT :batch_size
   ```
2. **Automatic Retry of Failed Purges**:
   Records marked as `ERROR` during a previous run are automatically included in subsequent batches, ensuring transient database errors or locks do not leave orphaned sensitive data.
3. **Per-Row Transaction Isolation**:
   Each event is minimized and committed individually (`await session.commit()`). An isolated malformed record logs an error, updates `anonymization_status = 'ERROR'`, and never halts batch execution.
4. **Non-Leaking Structured Metrics**:
   The job emits fixed-schema operational logs suitable for Prometheus / Loki collection:
   - `event_purge operation=purge outcome=success value=<count>`
   - `event_purge operation=purge outcome=error value=<count>`
   - `event_purge operation=lag outcome=oldest_pending_age_seconds value=<seconds>`

---

## 3. Analytics Replication & Historical Reconciliation

Replication to the analytics database is performed incrementally by `ReplicateAnalytics`:

1. **Idempotent Upsert (`ON CONFLICT (id) DO UPDATE`)**:
   Rather than `ON CONFLICT DO NOTHING`, `bulk_insert_events` performs an upsert:
   ```sql
   INSERT INTO event_store (id, organization_id, workflow_id, execution_id, created_at, event_type, event, anonymization_status)
   VALUES (...)
   ON CONFLICT (id) DO UPDATE SET
       event = EXCLUDED.event,
       anonymization_status = EXCLUDED.anonymization_status;
   ```
   This guarantees that historical replays or re-purged source records propagate updates to the destination analytics store without generating duplicates.
2. **Schema & Migration Parity**:
   The analytics database schema is maintained in strict lockstep with the primary operational database via `migration_service.auto_migrate_analytics()`.

---

## 4. API Consumption Contract (`GET /executions/{id}`)

When clients or webhook processors inspect a previously purged execution:
- The HTTP endpoint returns status **`200 OK`**.
- The response model includes an explicit field:
  ```json
  {
    "id": "e4b6c310-4bf6-4299-b1e7-a9a3de838505",
    "status": "SUCCESS",
    "purged": true,
    "data": {
      "total_processing_time_ms": 1450,
      "result": {
        "classification": null,
        "extraction": null,
        "barcodes": []
      }
    }
  }
  ```
- Clients can differentiate between an execution with no extracted data versus an execution whose payload has been expired and purged according to retention policy.
- Pydantic models decode sanitized envelopes without throwing validation errors.
