"""Regression tests for issue #132: worker reclaimer and DLQ guards.

Each test reproduces a defect against real Redis and is paired with a
mutation check (documented in the PR): reverting the fix makes it fail.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from document_ia_infra.redis.consumer import Consumer
from document_ia_infra.redis.serializable_message import SerializableMessage


class RecoveryMessage(SerializableMessage):
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def to_dict(self) -> dict[str, Any]:
        return self.payload

    @staticmethod
    def from_json(data: str) -> "RecoveryMessage":
        return RecoveryMessage(json.loads(data))


@pytest.fixture
async def redis_client() -> Redis:
    client = Redis.from_url("redis://localhost:6379/0", decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        pytest.skip(f"Redis not available: {exc}")
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def stream(redis_client: Redis) -> str:
    name = f"test-recovery:{uuid4()}"
    try:
        yield name
    finally:
        await redis_client.delete(name, f"{name}:dlq")


async def wait_until(
    predicate: Callable[[], Any], timeout: float = 5.0
) -> None:
    async with asyncio.timeout(timeout):
        while True:
            result = predicate()
            if asyncio.iscoroutine(result):
                result = await result
            if result:
                break
            await asyncio.sleep(0.02)


async def pending_count(redis: Redis, stream: str, group: str) -> int:
    info = await redis.xpending(stream, group)
    return info["pending"] if isinstance(info, dict) else info.pending


async def _pending_is_zero(redis: Redis, stream: str, group: str) -> bool:
    return await pending_count(redis, stream, group) == 0


async def pending_idle_ms(redis: Redis, stream: str, group: str) -> int:
    """Idle time (ms) of the first pending entry, per XPENDING."""
    entries = await redis.xpending_range(stream, group, min="-", max="+", count=1)
    if not entries:
        return 0
    first = entries[0]
    if isinstance(first, dict):
        return first.get("time_since_delivered", first.get("idle", 0))
    return first.time_since_delivered


def make_consumer(
    stream: str,
    group: str,
    handler: Callable[..., Awaitable[None]] | None = None,
) -> Consumer[RecoveryMessage]:
    async def noop(message: RecoveryMessage, retry_count: int, is_last: bool) -> None:
        return None

    return Consumer[RecoveryMessage](
        consumer_name=f"worker-{uuid4()}",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        message_class=RecoveryMessage,
        process_message_callable=handler or noop,
        worker_number=1,
        max_retry_number=3,
    )


def use_test_redis(monkeypatch: pytest.MonkeyPatch, redis_client: Redis) -> None:
    from document_ia_infra.redis import redis_manager as rm_module

    async def get_connection() -> Redis:
        return redis_client

    monkeypatch.setattr(rm_module.redis_manager, "get_connection", get_connection)


async def stop_tasks(consumer: Consumer, *tasks: asyncio.Task) -> None:
    consumer.stop_flag.set()
    consumer._listener_done.set()
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await asyncio.wait_for(task, timeout=2)
        except BaseException:
            pass
    consumer.executor.shutdown(wait=False)


@pytest.mark.asyncio
async def test_reclaimer_does_not_duplicate_in_flight_message(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow handler must not be reclaimed mid-processing (duplicate delivery).

    XAUTOCLAIM measures idle since delivery, not handler activity. Without the
    heartbeat, a healthy message whose processing exceeds RECLAIM_IDLE_MS is
    reclaimed by our own reclaimer and requeued: the handler runs twice.
    Mutation: removing the heartbeat makes this fail (a copy is created).
    """
    group = f"group-inflight-{uuid4()}"
    monkeypatch.setattr("document_ia_infra.redis.consumer.RECLAIM_IDLE_MS", 300)
    use_test_redis(monkeypatch, redis_client)

    deliveries: list[str] = []
    handler_started = asyncio.Event()
    release_handler = asyncio.Event()

    async def slow_handler(message: RecoveryMessage, rc: int, is_last: bool) -> None:
        deliveries.append(message.payload.get("payload", ""))
        handler_started.set()
        await asyncio.wait_for(release_handler.wait(), timeout=5)

    consumer = make_consumer(stream, group, slow_handler)
    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    await redis_client.xadd(
        stream, {"data": json.dumps({"payload": "slow"}), "retries": "0"}
    )

    listener = asyncio.create_task(consumer._start_listening_messages())
    reclaimer = asyncio.create_task(consumer._reclaim_pending_messages())
    heartbeat = asyncio.create_task(consumer._heartbeat_in_flight_entries())
    consumer.reclaimer_task = reclaimer
    try:
        await asyncio.wait_for(handler_started.wait(), timeout=5)
        # Let several idle thresholds elapse while the handler is stuck. The
        # reclaimer polls once per second, so allow enough passes that —
        # without the heartbeat — a reclaim would definitely have fired.
        await asyncio.sleep(2.5)
        # Positive control: the in-flight entry really is being processed
        # (it is pending), so without the heartbeat it would be reclaimable.
        assert await pending_count(redis_client, stream, group) == 1
        # The heartbeat must have kept idle below threshold: no requeue copy.
        entries = await redis_client.xrange(stream)
        copies = [f for _, f in entries if f.get("original_id")]
        assert copies == [], "a requeue copy was created while handler was active"
        # The heartbeat refreshed idleness: the pending entry's idle time must
        # stay below the reclaim threshold despite the long-running handler.
        idle = await pending_idle_ms(redis_client, stream, group)
        assert idle < 300, f"in-flight entry idle {idle}ms exceeded threshold"
        release_handler.set()
        await wait_until(lambda: _pending_is_zero(redis_client, stream, group))
        assert deliveries == ["slow"], "handler ran more than once"
    finally:
        release_handler.set()
        await stop_tasks(consumer, listener, reclaimer, heartbeat)


@pytest.mark.asyncio
async def test_requeue_is_idempotent_when_ack_fails(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed ACK after a requeue copy must not create a second copy.

    Mutation: removing the index-key guard makes a later reclaim create a
    second copy (unbounded duplicates, attempt budget never consumed).
    """
    group = f"group-idem-{uuid4()}"
    monkeypatch.setattr("document_ia_infra.redis.consumer.RECLAIM_IDLE_MS", 0)
    use_test_redis(monkeypatch, redis_client)
    consumer = make_consumer(stream, group)

    await redis_client.xadd(
        stream, {"data": json.dumps({"payload": "x"}), "retries": "0"}
    )
    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    resp = await redis_client.xreadgroup(
        groupname=group, consumername="dead-worker", streams={stream: ">"}, count=1
    )
    original_id = resp[0][1][0][0]

    original_xack = redis_client.xack
    ack_failures = 0

    async def fail_ack_once(stream_name: str, group_name: str, *ids: str) -> int:
        nonlocal ack_failures
        if stream_name == stream and original_id in ids and ack_failures == 0:
            ack_failures += 1
            raise ConnectionError("ack failed")
        return await original_xack(stream_name, group_name, *ids)

    monkeypatch.setattr(redis_client, "xack", fail_ack_once)

    reclaimer = asyncio.create_task(consumer._reclaim_pending_messages())
    try:
        # Pass 1: copy created, ACK fails -> original still pending.
        await wait_until(lambda: ack_failures == 1)
        assert await pending_count(redis_client, stream, group) == 1
        # Pass 2+: guard sees the copy exists -> ACK only, no second copy.
        await wait_until(lambda: _pending_is_zero(redis_client, stream, group))
        entries = await redis_client.xrange(stream)
        copies = [f for _, f in entries if f.get("original_id") == original_id]
        assert len(copies) == 1, "a second requeue copy was created"
        assert copies[0]["retries"] == "1"
        assert ack_failures == 1
    finally:
        await stop_tasks(consumer, reclaimer)


@pytest.mark.asyncio
async def test_dlq_retention_guard_fails_closed_when_scan_fails(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing DLQ idempotence scan must not write a second DLQ row.

    Mutation: restoring the fail-open guard (scan error -> "not retained")
    writes a second DLQ row and ACKs the original.
    """
    group = f"group-dlqfc-{uuid4()}"
    monkeypatch.setattr("document_ia_infra.redis.consumer.RECLAIM_IDLE_MS", 0)
    use_test_redis(monkeypatch, redis_client)
    consumer = make_consumer(stream, group)
    dlq = f"{stream}:dlq"

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    original_id = await redis_client.xadd(
        stream, {"data": json.dumps({"payload": "ex"}), "retries": "2"}
    )
    await redis_client.xreadgroup(
        groupname=group, consumername="dead-worker", streams={stream: ">"}, count=1
    )

    original_xack = redis_client.xack
    ack_failures = 0

    async def fail_ack_once(stream_name: str, group_name: str, *ids: str) -> int:
        nonlocal ack_failures
        if stream_name == stream and original_id in ids and ack_failures == 0:
            ack_failures += 1
            raise ConnectionError("ack failed")
        return await original_xack(stream_name, group_name, *ids)

    original_eval = redis_client.eval
    dlq_attempts = 0

    async def fail_second_dlq_eval(script: str, numkeys: int, *args: Any) -> Any:
        nonlocal dlq_attempts
        # The DLQ retention script targets the DLQ stream as its single key.
        if numkeys == 1 and args and args[0] == dlq:
            dlq_attempts += 1
            if dlq_attempts == 2:
                raise ConnectionError("dlq retention failed")
        return await original_eval(script, numkeys, *args)

    monkeypatch.setattr(redis_client, "xack", fail_ack_once)
    monkeypatch.setattr(redis_client, "eval", fail_second_dlq_eval)

    reclaimer = asyncio.create_task(consumer._reclaim_pending_messages())
    try:
        # Pass 1: retention confirmed, ACK fails -> one DLQ row, still pending.
        await wait_until(lambda: ack_failures == 1)
        assert await pending_count(redis_client, stream, group) == 1
        assert await redis_client.xlen(dlq) == 1
        # Pass 2: retention fails -> outcome unknown. No second row, no ACK.
        await wait_until(lambda: dlq_attempts >= 2)
        assert await redis_client.xlen(dlq) == 1
        assert await pending_count(redis_client, stream, group) == 1
        # Pass 3: retention succeeds (already present) -> ACK proceeds.
        await wait_until(lambda: _pending_is_zero(redis_client, stream, group))
        assert await redis_client.xlen(dlq) == 1
        retained = [
            f
            for _, f in await redis_client.xrange(dlq)
            if f.get("original_id") == original_id
        ]
        assert len(retained) == 1
    finally:
        await stop_tasks(consumer, reclaimer)


@pytest.mark.asyncio
async def test_dlq_retention_is_idempotent_and_complete(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DLQ retention must be exactly-once even beyond a 1000-entry scan window.

    The atomic Lua guard finds an existing original_id copy regardless of
    position, so a retained row past the first 1000 entries is still detected.
    Mutation: reverting to a bounded COUNT scan that declares absence on a
    truncated result writes a second DLQ row.
    """
    group = f"group-dlqcomplete-{uuid4()}"
    use_test_redis(monkeypatch, redis_client)
    consumer = make_consumer(stream, group)
    dlq = f"{stream}:dlq"

    msg_id = await redis_client.xadd(stream, {"data": "x", "retries": "0"})
    # 1000 unrelated DLQ rows, then the row that retains our message.
    for i in range(1000):
        await redis_client.xadd(dlq, {"original_id": f"other-{i}", "data": "x"})
    await redis_client.xadd(dlq, {"original_id": msg_id, "data": "x"})

    # A second retention must detect the existing row and not duplicate it.
    assert await consumer._send_to_dlq(
        redis_client, msg_id, {"data": "x", "retries": "0"}, "decode_error"
    )
    retained = [
        f
        for _, f in await redis_client.xrange(dlq)
        if f.get("original_id") == msg_id
    ]
    assert len(retained) == 1, "a second DLQ row was written past the scan window"
    consumer.executor.shutdown(wait=False)


@pytest.mark.asyncio
async def test_requeue_is_atomic_under_concurrent_reclaim(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent requeue attempts produce exactly one copy, no orphan window.

    The atomic Lua script checks-and-creates in one step: two overlapping
    attempts yield a single copy, and there is no separate reservation that
    could be orphaned by a crash between reserve and copy (message loss).
    Mutation: a non-atomic check-then-create lets both create a copy.
    """
    group = f"group-atomic-{uuid4()}"
    use_test_redis(monkeypatch, redis_client)
    consumer = make_consumer(stream, group)

    original_id = "1700000000000-0"
    await asyncio.gather(
        consumer._requeue_once(redis_client, original_id, "x", 1),
        consumer._requeue_once(redis_client, original_id, "x", 1),
    )
    entries = await redis_client.xrange(stream)
    copies = [f for _, f in entries if f.get("original_id") == original_id]
    assert len(copies) == 1, "concurrent requeues produced duplicate copies"
    consumer.executor.shutdown(wait=False)


@pytest.mark.asyncio
async def test_requeue_after_lost_response_does_not_duplicate(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lost XADD response must not cause a duplicate on the next attempt.

    Simulates a copy that was created but whose response was lost: the next
    requeue attempt finds the existing copy instead of creating a second.
    """
    group = f"group-lostresp-{uuid4()}"
    use_test_redis(monkeypatch, redis_client)
    consumer = make_consumer(stream, group)
    original_id = "1700000000000-0"

    # First attempt "succeeds server-side" (copy exists), then a second
    # attempt must not create another.
    await consumer._requeue_once(redis_client, original_id, "x", 1)
    await consumer._requeue_once(redis_client, original_id, "x", 1)
    entries = await redis_client.xrange(stream)
    copies = [f for _, f in entries if f.get("original_id") == original_id]
    assert len(copies) == 1, "a lost response led to a duplicate copy"
    consumer.executor.shutdown(wait=False)


@pytest.mark.asyncio
async def test_requeue_after_crash_creates_copy_no_message_loss(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed requeue must not leave durable state that suppresses the copy.

    The P1 finding: a SET NX reservation orphaned by a crash made another
    reclaimer ACK the original without creating a copy (message loss). The
    invariant that prevents it: a failed requeue attempt must leave no state
    other than (possibly) the copy itself, so the next attempt always creates
    the copy if it is absent.

    This test fails the first attempt after any reservation would be taken,
    then asserts the second attempt still creates exactly one copy and ACKs.
    Mutation (SET NX approach): the failed first attempt leaves a reservation
    key, the second attempt reads it as "copy exists" and skips the copy —
    the stream ends with no copy, so this test fails.
    """
    group = f"group-crash-{uuid4()}"
    monkeypatch.setattr("document_ia_infra.redis.consumer.RECLAIM_IDLE_MS", 0)
    use_test_redis(monkeypatch, redis_client)
    consumer = make_consumer(stream, group)

    await redis_client.xadd(
        stream, {"data": json.dumps({"payload": "x"}), "retries": "0"}
    )
    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    resp = await redis_client.xreadgroup(
        groupname=group, consumername="dead-worker", streams={stream: ">"}, count=1
    )
    original_id, fields = resp[0][1][0]
    consumer.redis = redis_client

    # Force the first attempt to fail after any reservation side effect. We
    # patch eval so the requeue's atomic step errors — but only after letting
    # a SET NX-style implementation take its reservation via `set`. The
    # atomic implementation performs a single eval and leaves nothing.
    original_eval = redis_client.eval
    attempts = 0

    async def fail_first_eval(script: str, numkeys: int, *args: Any) -> Any:
        nonlocal attempts
        if numkeys == 1 and args and args[0] == stream:
            attempts += 1
            if attempts == 1:
                raise ConnectionError("simulated crash during requeue")
        return await original_eval(script, numkeys, *args)

    monkeypatch.setattr(redis_client, "eval", fail_first_eval)

    # First attempt crashes -> original stays pending, no copy created.
    await consumer._reclaim_entry(original_id, dict(fields))
    assert await pending_count(redis_client, stream, group) == 1
    assert not [f for _, f in await redis_client.xrange(stream) if f.get("original_id")]

    # Second attempt recovers -> exactly one copy created, original ACKed.
    await consumer._reclaim_entry(original_id, dict(fields))
    assert await pending_count(redis_client, stream, group) == 0
    copies = [
        f for _, f in await redis_client.xrange(stream) if f.get("original_id") == original_id
    ]
    assert len(copies) == 1, "the message was lost: no requeue copy exists"
    consumer.executor.shutdown(wait=False)


@pytest.mark.asyncio
async def test_malformed_retries_routes_to_dlq(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable retries field is retained in DLQ, not re-claimed forever."""
    group = f"group-malformed-{uuid4()}"
    monkeypatch.setattr("document_ia_infra.redis.consumer.RECLAIM_IDLE_MS", 0)
    use_test_redis(monkeypatch, redis_client)
    consumer = make_consumer(stream, group)
    dlq = f"{stream}:dlq"

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    await redis_client.xadd(
        stream, {"data": json.dumps({"payload": "bad"}), "retries": "not-a-number"}
    )
    await redis_client.xreadgroup(
        groupname=group, consumername="dead-worker", streams={stream: ">"}, count=1
    )

    reclaimer = asyncio.create_task(consumer._reclaim_pending_messages())
    try:
        await wait_until(lambda: _pending_is_zero(redis_client, stream, group))
        assert await redis_client.xlen(dlq) == 1
        entries = await redis_client.xrange(dlq)
        assert entries[0][1]["reason"] == "max_retries_exceeded"
        assert "Malformed retries" in entries[0][1]["error"]
    finally:
        await stop_tasks(consumer, reclaimer)
