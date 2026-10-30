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
        keys = [name, f"{name}:dlq"]
        async for key in redis_client.scan_iter(f"{name}:requeued:*"):
            keys.append(key)
        await redis_client.delete(*keys)


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

    original_xrange = redis_client.xrange
    dlq_scans = 0

    async def fail_second_dlq_scan(*args: Any, **kwargs: Any) -> Any:
        nonlocal dlq_scans
        if args and args[0] == dlq:
            dlq_scans += 1
            if dlq_scans == 2:
                raise ConnectionError("dlq scan failed")
        return await original_xrange(*args, **kwargs)

    monkeypatch.setattr(redis_client, "xack", fail_ack_once)
    monkeypatch.setattr(redis_client, "xrange", fail_second_dlq_scan)

    reclaimer = asyncio.create_task(consumer._reclaim_pending_messages())
    try:
        # Pass 1: retention confirmed, ACK fails -> one DLQ row, still pending.
        await wait_until(lambda: ack_failures == 1)
        assert await pending_count(redis_client, stream, group) == 1
        assert await redis_client.xlen(dlq) == 1
        # Pass 2: DLQ scan fails -> retention unknown. No second row, no ACK.
        await wait_until(lambda: dlq_scans >= 2)
        assert await redis_client.xlen(dlq) == 1
        assert await pending_count(redis_client, stream, group) == 1
        # Pass 3: scan succeeds -> already retained, ACK proceeds.
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
async def test_dlq_scan_is_bounded(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DLQ idempotence scan must carry an upper bound / COUNT.

    Mutation: dropping COUNT from the XRANGE makes the recorded call unbounded.
    """
    group = f"group-bounded-{uuid4()}"
    consumer = make_consumer(stream, group)
    dlq = f"{stream}:dlq"
    calls: list[dict[str, Any]] = []
    original_xrange = redis_client.xrange

    async def spy_xrange(*args: Any, **kwargs: Any) -> Any:
        if args and args[0] == dlq:
            calls.append(kwargs)
        return await original_xrange(*args, **kwargs)

    monkeypatch.setattr(redis_client, "xrange", spy_xrange)

    msg_id = await redis_client.xadd(stream, {"data": "x", "retries": "0"})
    assert await consumer._send_to_dlq(
        redis_client, msg_id, {"data": "x", "retries": "0"}, "decode_error"
    )
    assert calls, "no DLQ scan recorded"
    for kwargs in calls:
        assert kwargs.get("max") == "+", "scan has no upper bound"
        assert kwargs.get("count") is not None, "scan has no COUNT bound"
    consumer.executor.shutdown(wait=False)


@pytest.mark.asyncio
async def test_requeue_guard_is_atomic_under_concurrent_reclaim(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent reclaimers of the same entry produce exactly one reservation.

    Covers the residual documented in #131: a read-then-write XRANGE guard is
    not atomic. The SET NX index key is atomic, so even two overlapping
    reclaim passes yield a single reservation.
    Mutation: a non-atomic read-then-write guard lets both observe absence.
    """
    group = f"group-atomic-{uuid4()}"
    use_test_redis(monkeypatch, redis_client)
    consumer = make_consumer(stream, group)

    original_id = "1700000000000-0"
    results = await asyncio.gather(
        consumer._already_requeued(redis_client, original_id),
        consumer._already_requeued(redis_client, original_id),
    )
    # Exactly one caller reserved the index (False = first copy); the other
    # observed it already exists (True).
    assert sorted(results) == [False, True], "both guards observed absence"
    consumer.executor.shutdown(wait=False)


@pytest.mark.asyncio
async def test_failed_xadd_releases_reservation_for_retry(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed XADD must free the index reservation so the retry copies.

    Without release, a copy that was never created would leave the key set
    and every later attempt would skip the requeue: message loss.
    """
    group = f"group-release-{uuid4()}"
    use_test_redis(monkeypatch, redis_client)
    consumer = make_consumer(stream, group)
    msg_id = "1700000000000-0"

    assert await consumer._already_requeued(redis_client, msg_id) is False
    key = consumer._requeue_index_key(msg_id)
    assert await redis_client.exists(key) == 1
    await consumer._release_requeue_reservation(redis_client, msg_id)
    assert await redis_client.exists(key) == 0
    # A fresh attempt can reserve again and create the copy.
    assert await consumer._already_requeued(redis_client, msg_id) is False
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
