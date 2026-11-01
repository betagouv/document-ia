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

Delivery is at-least-once, not exactly-once business execution. Atomic copy guards scan retained stream history; trimming away pending sources/copies invalidates that guard. Publishers never use MAXLEN; use the completion-aware retention procedure below. Heartbeats protect live handlers but are not fencing/leases against process pauses. See the worker README for the blocking-operation inventory.

## New-execution admission

`redis/admission.py` uses one Redis Lua operation to inspect both workflow and
webhook queues, check hysteresis and allocate a workflow slot by XADD. There is
no per-process counter or check/write gap between API instances. Retries and
webhook publications for already accepted work bypass new-execution admission
so they can drain. Both API and worker must use the same Redis database, stream
names and group names. Redis 7 or newer is required for consumer-group lag.

Each queue counts consumer-group lag plus pending (unacknowledged) entries, not
XLEN, which includes retained completed history. Before group creation all stream
entries count. The oldest pending or undelivered Redis entry supplies queue age,
using Redis's clock. An unknown lag, wrong key type or failed Redis operation
refuses new work; it never guesses that capacity is available. A lost XADD reply
remains an ambiguous publication, under the existing #120 contract, not a
cross-store transaction or exactly-once guarantee.

The same configurable thresholds apply independently to each queue:

| Setting | Default | Meaning |
| --- | --- | --- |
| `ADMISSION_MAX_OUTSTANDING` | 1000 | Stop new executions at this outstanding count |
| `ADMISSION_RESUME_OUTSTANDING` | 800 | Reopen only at or below this count |
| `ADMISSION_MAX_AGE_SECONDS` | 300 | Stop when the oldest queue entry reaches this age |
| `ADMISSION_RESUME_AGE_SECONDS` | 120 | Reopen only at or below this age |
| `ADMISSION_MAX_RETAINED` | 10000 | Stop at this combined source + DLQ entry count, per queue |
| `ADMISSION_RESUME_RETAINED` | 8000 | Reopen only at or below this retained count (minimum 1: cleanup keeps the last-delivered row) |

Once a queue closes admission, its outstanding count, age and retained count must fall to their resume
thresholds. The closed state is shared in `<stream>:admission`, without a TTL
that might reopen admission during an outage. ACKs reduce outstanding work;
there are no expiring leases that can forget an accepted job. A webhook backlog
can exceed its stop threshold while previously accepted workflows finish: their
notifications must not be discarded to enforce the new-work limit.

These are conservative starting values, not production-sized budgets. Before
deployment, choose counts/ages from measured peak traffic, worker latency,
dependency quotas, acceptable wait times and storage/memory headroom. A stalled
OCR, LLM, download, database write or webhook delivery is reflected by unfinished
queue work; this is not an active health probe or provider-specific circuit
breaker. Queue age is the age of the current delivery entry, not total execution
age across retries. Retained counts are a soft entry budget, not a byte limit:
retries and notifications of accepted work can still increase them. Retained
uploads and per-document byte budgets are separate storage policies. Do not use MAXLEN as an
admission limit or trim pending entries to reopen admission.

## Completion-aware retention

`STREAM_COMPLETED_RETENTION_SECONDS` defaults to one day and
`STREAM_DLQ_RETENTION_SECONDS` to seven days. They are minimum retention ages,
not guaranteed deletion deadlines. `EVENT_STREAM_EXPIRATION` and
`EVENT_STREAM_MAXLEN` remain legacy configuration only; never EXPIRE the stream.

Run from a deployed API/worker environment containing `document-ia-infra`, with
the same Redis settings as the consumers:

```bash
python -m document_ia_infra.redis.maintenance
python -m document_ia_infra.redis.maintenance --apply
```

The first command is read-only. The second deletes at most
`STREAM_CLEANUP_BATCH_SIZE` entries (default 100, maximum 1000) from each source
and each DLQ. Schedule that second command once per minute in the deployment's
scheduler, capture its JSON output and alert on a nonzero exit code. This PR
does not configure the production scheduler or enable cleanup automatically.
Use a shorter interval or larger batch only after measuring Redis latency and
the eligible backlog; do not loop unboundedly in a request or consumer handler.

Deletion and group checks are one Lua operation. A source entry is eligible only
before every group's last-delivered ID and oldest pending ID, and before its
age cutoff. Without a group there is no evidence of completion, so nothing is
deleted. Unknown lag or Redis errors stop cleanup. DLQ expiration also requires
the original to be in that safe completed prefix. A failed source ACK therefore
protects the DLQ copy used by the idempotence guard, even past seven days.
If the DLQ has consumer groups, their pending/undelivered boundary is protected
too. Old DLQ rows without an `original_id` require manual reconciliation.

Cleanup deliberately keeps the boundary row and can retain acknowledged history
behind an old pending entry. Each DLQ pass inspects only its oldest eligible-age
batch; protected rows can delay later cleanup. Alert on retained count and
oldest outstanding age instead of assuming an age setting bounds memory.
Do not destroy/reset groups or use manual XDEL/XTRIM to bypass this guard.

## Incident recovery and DLQ replay

1. Stop new traffic at the ingress while diagnosing the incident. Keep the
   shared admission state intact. Record queue counts/ages with the read-only
   command above, without copying document payloads into logs or tickets.
2. Repair Redis or the dependency. Before restarting **all** workflow and webhook
   consumers, set `STREAM_RECOVERY_INTERVAL_MS=1000`. Each stream then permits at
   most one new delivery and one pending claim per second across all instances;
   each returned batch contains one entry. This is a dispatch limit, not a limit
   on inline webhook retries or already-running handlers. Keep worker counts and
   webhook backoff consistent with the provider's quotas.
3. Let already accepted work drain. New workflow requests remain subject to
   outstanding-count, age and retained-history hysteresis. Recovery does not
   clear those thresholds. Run safe cleanup if completed history is the blocker.
4. Inspect a failed execution through the authorized API/Event Store. Determine
   whether repeating its external effects is safe and whether its uploaded
   object still exists. Fix permanent failures before considering replay.
   The DLQ is not a complete workflow backup and cannot restore deleted objects.
5. For a failed **workflow**, do not replay its Redis entry: the latest
   PostgreSQL event may be terminal and the worker would refuse to run its steps.
   After the service owner authorizes a new attempt and checks duplicate effects,
   submit a **new execution** through the authenticated API, using the original
   document and workflow parameters obtained through authorized access. A new
   upload may be necessary; the DLQ cannot reconstruct a deleted object. Keep
   the original DLQ row for investigation under the configured retention policy.
   The CLI and Python replay entry point explicitly refuse workflow streams
   without inserting a retry or deleting the DLQ row.

   For a **webhook**, replay one chosen DLQ entry from a restricted terminal:

```bash
python -m document_ia_infra.redis.maintenance --apply --stream webhook_stream --replay-id '<dlq-entry-id>'
```

Use the configured webhook stream name, not a DLQ name. Replay
requires the original to be delivered and no longer pending in every group.
DLQs with consumer groups need separate reconciliation and are refused.
The same admission check as new executions applies to webhook replay.
Insertion and deletion of the DLQ row are atomic: retrying after a lost reply
cannot create another copy from that row. Global manual replay is limited to
one per stream per second (or the larger recovery interval). Attempt count
resets to zero; `replayed_from` records the DLQ ID. There is no bulk-replay flag.
Webhook replay does not guarantee exactly-once notification effects.

6. Check counts, ages, failure rates and dependency latency after each small
   sample. Increase throughput by lowering the recovery interval only after
   observing stability; restore zero and restart all consumers when normal
   capacity is demonstrated. Stop the sample if failure/retention errors rise.

### Failure classes and monitoring

`classify_failure` labels known transport failures, timeouts, HTTP 408/425/429
and 5xx, and explicit `RetryableException` as temporary. HTTP 4xx outside that
set, known authentication errors and invalid values are permanent. Other
exceptions are internal: they are not retried blindly. Worker automatic retries
remain restricted to explicit `RetryableException`, using the existing attempt
budget and WorkflowManager's notification contract. Raw dependency exceptions
can be labelled temporary but still require a new authorized execution; classification
does not silently change terminal workflow decisions. Other worker failures
require DLQ retention before ACK. Webhook HTTP retries use the same status classification;
non-HTTP webhook errors still remain pending for Redis recovery. Existing steps
that wrap an error in `RetryableException` explicitly retain their retry contract;
classification cannot recover a status or cause discarded by those steps.

The maintenance JSON exposes `pending`, `lag`, `oldest_outstanding_ms`,
`retained`, `dlq`, `completed_eligible` and `dlq_eligible` for each queue.
The last two count deletions on an apply pass and candidates on a read-only pass.
For several groups, pending/lag are summed deliveries, not unique jobs.
The fixed-schema `redis_delivery` log events supply counters by stream,
operation and outcome: `retry`/`dlq` created/existing/error, `reclaim` success
(value = claimed entries), `ack` success/error, and worker `failure`
temporary/permanent/internal. Aggregate these in the existing log collector;
no Prometheus endpoint or Redis-backed counter is added. Payloads, exception
messages and document identifiers are not metric labels. Restricted DLQ storage
still contains messages; do not export it to the log collector.

### Deployment checklist and limits

Before production, record the actual Redis plan/memory, `maxmemory-policy`,
persistence/replication settings and backup restore test with the operator.
Use **noeviction**, never a key-eviction policy: losing an entire stream or
admission key would invalidate accepted-work retention. Configure provider
memory/disk alerts and reserve headroom for draining already accepted work,
Lua copy scans, replication and persistence buffers. Size the soft entry
budgets from measured entry sizes and traffic, with both API and worker using
identical settings. Counts do not impose a hard byte or tenant quota.

No production configuration was inspected or changed here. A DLQ in the same
Redis database is **not** an independent fallback if Redis refuses writes or
loses data. On a failed DLQ write the source stays pending; ACK is not evidence
of durable replication. Recovery guarantees depend on the deployment's Redis
durability configuration. For incident triage the proposed policy keeps failures
in Redis for at least seven days; no long-term document archive is required by
this change. If the service owner requires longer retention or survival of
Redis loss, provide an independently durable, access-controlled export with a
restore test before enabling expiration; simply raising a TTL is insufficient.
Object-storage retention remains outside this Redis policy.
