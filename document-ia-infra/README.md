# Document IA Infrastructure

This project contains shared code about infrastructure components for documentIA projects.

## Persisted event decoding

`data/event/schema/mappers/event_mapper.py::convert_inner_event_dto` is the shared
decoder for the four persisted workflow event types. `convert_event_dto` adds the
store envelope; the worker and API also use the decoder directly. Pydantic event
schemas retain responsibility for nested extraction and barcode decoding. API
response projection and debug filtering remain in `ExecutionService`, also used
by webhook notifications.

`decode_event_dto` is the entry point for persisted DTOs in the store service,
API/webhooks and worker. It checks that execution, workflow and organization IDs
agree between envelope and payload (organization IDs are compared as UUIDs).
Each concrete schema fixes its event type with `Literal`; an explicit payload
type must match the envelope. An omitted payload type still defaults to the
envelope-selected schema for legacy compatibility. Store row IDs and timestamps
are independent of payload event IDs and timestamps and are not compared.
Decoder errors identify mismatched field names, never their values; schema
errors use a generic message to avoid logging document contents.

### Event representations and versions

- `EventEntity` is the SQLAlchemy storage row. Its `id` and `created_at` identify
  the row and its persistence time. `EventRepository._to_dto` is the single
  storage-to-transport envelope conversion.
- `EventDTO` transports that envelope plus the raw JSON payload between the
  repository and decoders. `EventStoreRecord` combines the same storage envelope
  with a decoded `BaseEvent`; neither representation aliases payload metadata.
- `BaseEvent` is the domain representation. Its `event_id` and `created_at` are
  the domain event ID and occurrence time, which can legitimately differ from
  the storage row metadata. API response models remain separate projections.
- The persisted payload key `version` is the **workflow definition version**
  used to select v1/v2 execution semantics. `workflow_version` names that role
  in Python without adding a serialized field. It is neither a payload schema
  version nor an optimistic-concurrency token; no such tokens are merged into
  it. Schema compatibility remains the decoder and Pydantic models' concern.

`DocumentExtraction` resolves and validates typed extraction properties once.
`ExecutionService` only projects those decoded properties to `GenericProperty`
for API responses; it does not resolve the schema or reconstruct the model a
second time. Historical API and webhook golden fixtures cover this boundary.

For malformed persisted start parameters, validation now occurs with the full
start event: worker failure records identify `parse_start_event` instead of
`prepare_workflow`, without including the invalid parameter value.

Synthetic historical-shape fixtures live in `tests/fixtures/persisted_events.json`.
API golden payloads were captured from parent commit `e54d117`, before migrating
callers, and cover normal/debug output and webhook JSON. These fixtures are
synthetic, not a production-data audit. Before deploying stricter rejection,
check representative historical rows in the target environment for envelope/type
and identifier consistency; no production database was accessed for these tests.

## Redis delivery and execution responsibilities

- `redis/stream_delivery.py`: concrete group/read/claim/ACK/idle-refresh operations and atomic, idempotent copy-before-ACK primitives shared by the worker and API. A failed or cancelled copy is **not** confirmation: do not ACK on that evidence alone (the worker failure policy may instead confirm terminal DLQ retention); a lost successful response is safe to retry. DLQ scans cover the whole target stream because source and target IDs have independent sequences.
- `redis/handler_execution.py`: owns the worker thread pool and per-message `asyncio.Runner`. Reads are bounded by `min(batch_size, worker_number - active_handlers)`; no reads when full. Both values must be positive. This is not an async-only handler runner: workflow CPU/blocking work must remain off the delivery loop.
- `redis/worker_error_policy.py`: worker retryable failures create Redis copies, with `retries` counting consumed attempts and `max_retry_number` the total attempt budget. Fatal/exhausted/decode failures require confirmed DLQ retention before ACK. API HTTP backoff remains a distinct policy in the API package, not a universal consumer base class.
- `redis/consumer.py`: orchestration of listener, reclaimer, heartbeat and bounded drain. The heartbeat refreshes tracked in-flight/claimed work, including the existing shutdown drain. Worker handler IDs leave tracking before result handling/retention; this refactor preserves that boundary rather than extending heartbeat coverage. Running native/thread work cannot be interrupted by cancelling a Future; the worker process owner enforces its existing final shutdown deadline and leaves unfinished entries pending.

`StreamDelivery`, consumers and publishers **borrow** Redis clients/managers. The creator owns closure on the same event loop: worker runtime closes its main-loop manager; API lifespan closes its shared application manager after stopping consumers; each workflow closes its own webhook-publisher manager. `RedisManager.close()` closes both client and explicitly created connection pool, then resets state, and is idempotent. Stopping one consumer must not close another consumer/publisher's borrowed manager.

`OpenAIManager` creates a request-scoped `AsyncOpenAI` client on the request's loop and closes it with an async context manager on success, errors and cancellation. Merely constructing a manager/unused LLM step opens no client. HTTP download/OCR clients already use async context managers; workflow database sessions/engines are scoped and disposed by the workflow owner. Thread-loop teardown does not call `gc.collect()` to schedule client destructors.

Delivery is at-least-once, not exactly-once business execution. Atomic copy guards scan retained stream history; trimming away pending sources/copies invalidates that guard. Current publisher MAXLEN retention and no-progress deadlines need separate operational policies; this refactor does not redesign them. Heartbeats protect live handlers but are not fencing/leases against process pauses. See the worker README for the blocking-operation inventory.
