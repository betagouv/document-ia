"""Integration tests for SimpleStreamConsumer crash recovery (issue #112).

Covers the recovery of entries left pending by a stopped or crashed API
instance: XAUTOCLAIM-based reclaim by a live instance, per-instance
consumer identities, idempotent DLQ retention for exhausted entries, no
requeue of successfully delivered entries, heartbeat protection of in-flight
batches (including during shutdown drain) and of reclaimer work, fail-closed
behavior of the requeue idempotency guard, and start_from handling at group
creation.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from time import monotonic
from typing import Any, Awaitable, Callable
from uuid import uuid4

import httpx
import pytest
from redis.asyncio import Redis

from document_ia_api.infra.redis.simple_stream_consumer import (
    SimpleStreamConsumer,
    build_instance_consumer_name,
)
from document_ia_infra.redis.serializable_message import SerializableMessage


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass
class TestRecoveryMessage(SerializableMessage):
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"content": self.content}

    @staticmethod
    def from_json(data: str) -> "TestRecoveryMessage":
        payload = json.loads(data)
        return TestRecoveryMessage(content=payload["content"])


async def _wait_until(
    predicate: Callable[[], Awaitable[bool]] | Callable[[], bool],
    *,
    timeout: float = 5.0,
    interval: float = 0.05,
) -> None:
    start = monotonic()
    while True:
        result = predicate()
        if asyncio.iscoroutine(result) or asyncio.isfuture(result):
            result = await result
        if result:
            return
        if monotonic() - start > timeout:
            raise AssertionError("Timed out while waiting for predicate to be true")
        await asyncio.sleep(interval)


async def _pending_count(redis: Redis, stream: str, group: str) -> int:
    info = await redis.xpending(stream, group)
    return info["pending"] if isinstance(info, dict) else info.pending


async def _dlq_len(redis: Redis, stream: str) -> int:
    return await redis.xlen(f"{stream}:dlq")


def _pending_is_zero_pred(
    redis: Redis, stream: str, group: str
) -> Callable[[], Awaitable[bool]]:
    async def _predicate() -> bool:
        return (await _pending_count(redis, stream, group)) == 0

    return _predicate


def _dlq_len_is_pred(
    redis: Redis, stream: str, expected: int
) -> Callable[[], Awaitable[bool]]:
    async def _predicate() -> bool:
        return (await _dlq_len(redis, stream)) == expected

    return _predicate


async def _add_entry(
    redis: Redis, stream: str, content: str, retries: str = "0"
) -> str:
    return await redis.xadd(
        stream, {"data": json.dumps({"content": content}), "retries": retries}
    )


async def _deliver_to_dead_consumer(
    redis: Redis, stream: str, group: str, consumer: str = "dead-consumer"
) -> None:
    """Simulate an instance that reads an entry then dies before the ACK."""
    response = await redis.xreadgroup(
        group, consumer, streams={stream: ">"}, count=10, block=10
    )
    assert response, "dead consumer should have received the entry"


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_api_key_service_auth() -> None:
    """Recovery tests do not exercise API authentication or the DB."""


@pytest.fixture(autouse=True)
def use_test_redis(monkeypatch: pytest.MonkeyPatch, redis_client: Redis) -> None:
    from document_ia_infra.redis import redis_manager as redis_manager_module

    async def get_connection() -> Redis:
        return redis_client

    monkeypatch.setattr(
        redis_manager_module.redis_manager, "get_connection", get_connection
    )


@pytest.fixture
async def redis_client() -> Redis:
    redis_url = "redis://localhost:6379/0"
    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:  # pragma: no cover - infra dependency
        pytest.skip(f"Redis not available at {redis_url}: {exc}")
    try:
        yield client
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reclaimer_recovers_entry_of_dead_instance(
    redis_client: Redis,
) -> None:
    """An entry read but never acked by a dead instance is requeued and delivered."""
    stream = f"test_recovery_dead_instance:{uuid4()}"
    group = f"group-recovery-dead-{uuid4()}"
    handler_called = asyncio.Event()
    delivered: list[str] = []

    async def handler(message: TestRecoveryMessage) -> None:
        delivered.append(message.content)
        handler_called.set()

    consumer = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-live-{uuid4()}",
        block_ms=10,
        reclaim_idle_ms=100,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    await _add_entry(redis_client, stream, "dead-instance")
    await _deliver_to_dead_consumer(redis_client, stream, group)
    assert await _pending_count(redis_client, stream, group) == 1

    await consumer.start()
    try:
        await asyncio.wait_for(handler_called.wait(), timeout=10)
        await _wait_until(
            _pending_is_zero_pred(redis_client, stream, group), timeout=10
        )
        assert delivered == ["dead-instance"]
        assert await _dlq_len(redis_client, stream) == 0
        # Exactly one requeue copy was added, consuming a single attempt.
        entries = await redis_client.xrange(stream)
        assert len(entries) == 2
        retries_values = {fields.get("retries") for _, fields in entries}
        assert retries_values == {"0", "1"}
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_reclaimer_does_not_duplicate_in_flight_batch(
    redis_client: Redis,
) -> None:
    """Entries of a healthy in-flight batch are never reclaimed as duplicates.

    XAUTOCLAIM measures time since delivery, not handler activity: without
    the in-flight heartbeat, a slow first handler in a multi-entry batch
    lets the reclaimer copy and redeliver entries the main loop is still
    processing.
    """
    stream = f"test_recovery_in_flight:{uuid4()}"
    group = f"group-in-flight-{uuid4()}"
    calls: list[str] = []
    all_done = asyncio.Event()

    async def handler(message: TestRecoveryMessage) -> None:
        calls.append(message.content)
        if message.content == "slow-first":
            await asyncio.sleep(1.3)
        if len(calls) == 2:
            all_done.set()

    consumer = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-in-flight-{uuid4()}",
        block_ms=10,
        reclaim_idle_ms=100,
        count=50,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    await _add_entry(redis_client, stream, "slow-first")
    await _add_entry(redis_client, stream, "fast-second")

    await consumer.start()
    try:
        await asyncio.wait_for(all_done.wait(), timeout=10)
        # Let several reclaimer passes run past the slow handler duration.
        await asyncio.sleep(3)
        assert sorted(calls) == ["fast-second", "slow-first"]
        assert len(calls) == 2
        assert await redis_client.xlen(stream) == 2
        assert await _pending_count(redis_client, stream, group) == 0
        assert await _dlq_len(redis_client, stream) == 0
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_requeue_is_idempotent_when_ack_fails(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A requeued copy is never duplicated when the original's ACK fails.

    The requeue XADD and the original's XACK are separate commands: if the
    ACK fails, the original stays pending and is reclaimed again. The
    `original_id` guard must prevent a second copy and only retry the ACK.
    """
    stream = f"test_recovery_requeue_idem:{uuid4()}"
    group = f"group-requeue-idem-{uuid4()}"
    delivered: list[str] = []
    handler_called = asyncio.Event()

    async def handler(message: TestRecoveryMessage) -> None:
        delivered.append(message.content)
        handler_called.set()

    consumer = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-requeue-idem-{uuid4()}",
        block_ms=10,
        reclaim_idle_ms=100,
        max_retries=3,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    original_id = await _add_entry(redis_client, stream, "requeue-once")
    await _deliver_to_dead_consumer(redis_client, stream, group)
    assert await _pending_count(redis_client, stream, group) == 1

    original_xack = redis_client.xack
    ack_failures = 0

    async def fail_ack_once_for_original(
        stream_name: str, group_name: str, *entry_ids: str
    ) -> int:
        nonlocal ack_failures
        if stream_name == stream and original_id in entry_ids and ack_failures == 0:
            ack_failures += 1
            raise ConnectionError("redis ack failed")
        return await original_xack(stream_name, group_name, *entry_ids)

    monkeypatch.setattr(redis_client, "xack", fail_ack_once_for_original)

    await consumer.start()
    try:
        await asyncio.wait_for(handler_called.wait(), timeout=10)
        await _wait_until(
            _pending_is_zero_pred(redis_client, stream, group), timeout=10
        )
        entries = await redis_client.xrange(stream)
        assert len(entries) == 2
        copies = [
            fields for _, fields in entries if fields.get("original_id") == original_id
        ]
        assert len(copies) == 1
        assert copies[0]["retries"] == "1"
        assert delivered == ["requeue-once"]
        assert ack_failures == 1
        assert await _dlq_len(redis_client, stream) == 0
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_live_instance_recovers_entry_abandoned_by_another_instance(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient failure on instance A is recovered, possibly by instance B."""
    stream = f"test_recovery_two_instances:{uuid4()}"
    group = f"group-two-instances-{uuid4()}"
    calls: list[tuple[str, str]] = []
    failed_once = {"a": False}
    a_failed = asyncio.Event()
    success = asyncio.Event()

    async def handler_a(message: TestRecoveryMessage) -> None:
        if not failed_once["a"]:
            failed_once["a"] = True
            calls.append(("a", "fail"))
            a_failed.set()
            request = httpx.Request("POST", "http://localhost:1/webhook")
            raise httpx.ConnectError("connection refused", request=request)
        calls.append(("a", "success"))
        success.set()

    async def handler_b(message: TestRecoveryMessage) -> None:
        calls.append(("b", "success"))
        success.set()

    name_a = build_instance_consumer_name("api-webhook-consumer-a")
    name_b = build_instance_consumer_name("api-webhook-consumer-b")
    assert name_a != name_b

    consumer_a = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler_a,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=name_a,
        block_ms=10,
        reclaim_idle_ms=10_000,
    )
    consumer_b = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler_b,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=name_b,
        block_ms=10,
        reclaim_idle_ms=100,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    original_xreadgroup = redis_client.xreadgroup
    first_read_started = asyncio.Event()

    async def record_read(*args: Any, **kwargs: Any) -> Any:
        first_read_started.set()
        return await original_xreadgroup(*args, **kwargs)

    monkeypatch.setattr(redis_client, "xreadgroup", record_read)
    await consumer_a.start()
    try:
        await asyncio.wait_for(first_read_started.wait(), timeout=5)
        await _add_entry(redis_client, stream, "two-instances")
        await asyncio.wait_for(a_failed.wait(), timeout=5)
        assert await _pending_count(redis_client, stream, group) == 1

        await consumer_b.start()
        try:
            await asyncio.wait_for(success.wait(), timeout=15)
            await _wait_until(
                _pending_is_zero_pred(redis_client, stream, group), timeout=10
            )
            outcomes = sorted(calls)
            assert outcomes in (
                [("a", "fail"), ("a", "success")],
                [("a", "fail"), ("b", "success")],
            )
            assert await _dlq_len(redis_client, stream) == 0
            consumers = await redis_client.xinfo_consumers(stream, group)
            names = {c["name"] for c in consumers}
            assert {name_a, name_b} <= names
        finally:
            await consumer_b.stop()
    finally:
        await consumer_a.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_reclaimer_dlqs_exhausted_entry_exactly_once(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exhausted reclaimed entry is retained once in the DLQ, even if the
    first ACK after retention fails and a later pass reclaims it again."""
    stream = f"test_recovery_exhausted:{uuid4()}"
    group = f"group-exhausted-{uuid4()}"
    handler_called = asyncio.Event()

    async def handler(message: TestRecoveryMessage) -> None:
        handler_called.set()

    consumer = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-exhausted-{uuid4()}",
        block_ms=10,
        reclaim_idle_ms=100,
        max_retries=3,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    await _add_entry(redis_client, stream, "exhausted", retries="2")
    await _deliver_to_dead_consumer(redis_client, stream, group)

    original_xack = redis_client.xack
    ack_failures = 0

    async def fail_ack_once(stream_name: str, group_name: str, *entry_ids: str) -> int:
        nonlocal ack_failures
        if stream_name == stream and ack_failures == 0:
            ack_failures += 1
            raise ConnectionError("redis ack failed")
        return await original_xack(stream_name, group_name, *entry_ids)

    monkeypatch.setattr(redis_client, "xack", fail_ack_once)

    await consumer.start()
    try:
        await _wait_until(_dlq_len_is_pred(redis_client, stream, 1), timeout=10)
        await _wait_until(
            _pending_is_zero_pred(redis_client, stream, group), timeout=10
        )
        assert not handler_called.is_set()
        assert await _dlq_len(redis_client, stream) == 1
        assert ack_failures == 1
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_reclaimer_does_not_resend_delivered_entries(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successfully delivered and acked entry is never reclaimed or requeued."""
    stream = f"test_recovery_no_resend:{uuid4()}"
    group = f"group-no-resend-{uuid4()}"
    delivered: list[str] = []
    handler_called = asyncio.Event()

    async def handler(message: TestRecoveryMessage) -> None:
        delivered.append(message.content)
        handler_called.set()

    consumer = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-no-resend-{uuid4()}",
        block_ms=10,
        reclaim_idle_ms=100,
    )

    original_xack = redis_client.xack
    acknowledged = asyncio.Event()

    async def record_ack(stream_name: str, group_name: str, *entry_ids: str) -> int:
        result = await original_xack(stream_name, group_name, *entry_ids)
        acknowledged.set()
        return result

    monkeypatch.setattr(redis_client, "xack", record_ack)

    await consumer.start()
    try:
        await _add_entry(redis_client, stream, "delivered-once")
        await asyncio.wait_for(handler_called.wait(), timeout=5)
        await asyncio.wait_for(acknowledged.wait(), timeout=5)
        # Let at least two reclaimer passes run after the ACK.
        await asyncio.sleep(3)
        assert delivered == ["delivered-once"]
        assert await redis_client.xlen(stream) == 1
        assert await _pending_count(redis_client, stream, group) == 0
        assert await _dlq_len(redis_client, stream) == 0
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_start_from_dollar_skips_existing_history(
    redis_client: Redis,
) -> None:
    """A fresh group created at '$' does not replay pre-existing entries."""
    stream = f"test_recovery_start_dollar:{uuid4()}"
    group = f"group-start-dollar-{uuid4()}"
    handler_called = asyncio.Event()

    async def handler(message: TestRecoveryMessage) -> None:
        handler_called.set()

    entry_id = await _add_entry(redis_client, stream, "history")

    consumer = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-start-dollar-{uuid4()}",
        block_ms=10,
        reclaim_idle_ms=100,
        start_from="$",
    )

    await consumer.start()
    try:
        await asyncio.sleep(1.5)
        assert not handler_called.is_set()
        groups = await redis_client.xinfo_groups(stream)
        info = next(g for g in groups if g["name"] == group)
        assert info["last-delivered-id"] == entry_id
        assert await _pending_count(redis_client, stream, group) == 0
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_start_from_zero_delivers_existing_history(
    redis_client: Redis,
) -> None:
    """A fresh group created at '0-0' delivers pre-existing entries."""
    stream = f"test_recovery_start_zero:{uuid4()}"
    group = f"group-start-zero-{uuid4()}"
    delivered: list[str] = []
    handler_called = asyncio.Event()

    async def handler(message: TestRecoveryMessage) -> None:
        delivered.append(message.content)
        handler_called.set()

    await _add_entry(redis_client, stream, "history")

    consumer = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-start-zero-{uuid4()}",
        block_ms=10,
        reclaim_idle_ms=100,
        start_from="0-0",
    )

    await consumer.start()
    try:
        await asyncio.wait_for(handler_called.wait(), timeout=5)
        assert delivered == ["history"]
        await _wait_until(_pending_is_zero_pred(redis_client, stream, group), timeout=5)
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_heartbeat_protects_batch_during_shutdown_drain(
    redis_client: Redis,
) -> None:
    """A graceful stop does not expose the draining batch to another instance.

    stop() sets the shared stop event before awaiting the main loop, which
    keeps processing its current batch. If the heartbeat honored the stop
    event immediately, the batch's idle time would grow and another
    instance's reclaimer could requeue entries still being handled: a
    duplicate delivery during a clean shutdown.
    """
    stream = f"test_recovery_shutdown_drain:{uuid4()}"
    group = f"group-shutdown-drain-{uuid4()}"
    calls: list[str] = []
    handler_started = asyncio.Event()

    async def handler_a(message: TestRecoveryMessage) -> None:
        calls.append("a")
        handler_started.set()
        await asyncio.sleep(2.5)

    async def handler_b(message: TestRecoveryMessage) -> None:
        calls.append("b")

    consumer_a = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler_a,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-drain-a-{uuid4()}",
        block_ms=10,
        reclaim_idle_ms=100,
    )
    consumer_b = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler_b,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-drain-b-{uuid4()}",
        block_ms=10,
        reclaim_idle_ms=100,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    await _add_entry(redis_client, stream, "draining")

    await consumer_a.start()
    try:
        await asyncio.wait_for(handler_started.wait(), timeout=5)
        await consumer_b.start()
        try:
            # Blocks until A's batch has drained (~2.5s): B's reclaimer
            # polls several times inside that window.
            await consumer_a.stop()
            assert calls == ["a"]
            assert await redis_client.xlen(stream) == 1
            assert await _pending_count(redis_client, stream, group) == 0
            assert await _dlq_len(redis_client, stream) == 0
        finally:
            await consumer_b.stop()
    finally:
        await consumer_a.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_requeue_guard_fails_closed_when_scan_fails(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing idempotency scan never creates a second requeue copy.

    After a requeue whose ACK failed, the original stays pending. If the
    guard's XRANGE then errors on a later pass, "scan failed" must be
    treated as "unknown", not "no copy exists": the original is left
    pending and the next pass retries, instead of blindly requeueing a
    second copy.
    """
    stream = f"test_recovery_guard_fail_closed:{uuid4()}"
    group = f"group-guard-fail-closed-{uuid4()}"
    delivered: list[str] = []
    handler_called = asyncio.Event()

    async def handler(message: TestRecoveryMessage) -> None:
        delivered.append(message.content)
        handler_called.set()

    consumer = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-guard-fail-{uuid4()}",
        block_ms=10,
        reclaim_idle_ms=100,
        max_retries=3,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    original_id = await _add_entry(redis_client, stream, "fail-closed")
    await _deliver_to_dead_consumer(redis_client, stream, group)
    assert await _pending_count(redis_client, stream, group) == 1

    original_xack = redis_client.xack
    ack_failures = 0

    async def fail_ack_once_for_original(
        stream_name: str, group_name: str, *entry_ids: str
    ) -> int:
        nonlocal ack_failures
        if stream_name == stream and original_id in entry_ids and ack_failures == 0:
            ack_failures += 1
            raise ConnectionError("redis ack failed")
        return await original_xack(stream_name, group_name, *entry_ids)

    original_xrange = redis_client.xrange
    guard_scans = 0

    async def fail_second_guard_scan(*args: Any, **kwargs: Any) -> Any:
        nonlocal guard_scans
        if args and args[0] == stream and "min" in kwargs:
            guard_scans += 1
            if guard_scans == 2:
                raise ConnectionError("redis scan failed")
        return await original_xrange(*args, **kwargs)

    monkeypatch.setattr(redis_client, "xack", fail_ack_once_for_original)
    monkeypatch.setattr(redis_client, "xrange", fail_second_guard_scan)

    await consumer.start()
    try:
        await asyncio.wait_for(handler_called.wait(), timeout=10)
        await _wait_until(
            _pending_is_zero_pred(redis_client, stream, group), timeout=10
        )
        entries = await redis_client.xrange(stream)
        assert len(entries) == 2
        copies = [
            fields for _, fields in entries if fields.get("original_id") == original_id
        ]
        assert len(copies) == 1
        assert copies[0]["retries"] == "1"
        assert delivered == ["fail-closed"]
        assert ack_failures == 1
        assert guard_scans >= 3
        assert await _dlq_len(redis_client, stream) == 0
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.parametrize("retries_value", ["2", "bad"])
@pytest.mark.asyncio
async def test_dlq_retention_guard_fails_closed_when_scan_fails(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
    retries_value: str,
) -> None:
    """A failing DLQ idempotence scan never writes a second DLQ row.

    After a DLQ retention whose ACK failed, the original stays pending. If
    the retention guard's XRANGE then errors on a later pass, "scan failed"
    must be treated as "retention unknown", not "not retained": the entry
    is left pending without a second DLQ write, and the next pass retries.
    Covers both DLQ routes: exhausted entries and malformed retries fields.
    """
    stream = f"test_recovery_dlq_guard_fail_closed:{uuid4()}"
    group = f"group-dlq-guard-fail-closed-{uuid4()}"
    dlq_stream = f"{stream}:dlq"

    async def handler(message: TestRecoveryMessage) -> None:
        pass

    consumer = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-dlq-guard-fail-{uuid4()}",
        block_ms=10,
        reclaim_idle_ms=100,
        max_retries=3,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    original_id = await redis_client.xadd(
        stream,
        {"data": json.dumps({"content": "exhausted"}), "retries": retries_value},
    )
    await _deliver_to_dead_consumer(redis_client, stream, group)
    assert await _pending_count(redis_client, stream, group) == 1

    original_xack = redis_client.xack
    ack_failures = 0

    async def fail_ack_once_for_original(
        stream_name: str, group_name: str, *entry_ids: str
    ) -> int:
        nonlocal ack_failures
        if stream_name == stream and original_id in entry_ids and ack_failures == 0:
            ack_failures += 1
            raise ConnectionError("redis ack failed")
        return await original_xack(stream_name, group_name, *entry_ids)

    original_xrange = redis_client.xrange
    guard_scans = 0

    async def fail_second_dlq_guard_scan(*args: Any, **kwargs: Any) -> Any:
        nonlocal guard_scans
        if args and args[0] == dlq_stream and "min" in kwargs:
            guard_scans += 1
            if guard_scans == 2:
                raise ConnectionError("redis scan failed")
        return await original_xrange(*args, **kwargs)

    monkeypatch.setattr(redis_client, "xack", fail_ack_once_for_original)
    monkeypatch.setattr(redis_client, "xrange", fail_second_dlq_guard_scan)

    await consumer.start()
    try:
        # Pass 1: retention succeeds, ACK fails -> one DLQ row, still pending.
        await _wait_until(_dlq_len_is_pred(redis_client, stream, 1), timeout=10)
        assert await _pending_count(redis_client, stream, group) == 1

        # Pass 2: DLQ scan fails -> retention unknown. No second DLQ row,
        # no ACK: the entry must stay pending with a single DLQ row.
        await _wait_until(lambda: guard_scans >= 2, timeout=10)
        assert await _dlq_len(redis_client, stream) == 1
        assert await _pending_count(redis_client, stream, group) == 1

        # Pass 3: scan succeeds again -> already retained, ACK proceeds.
        await _wait_until(
            _pending_is_zero_pred(redis_client, stream, group), timeout=10
        )
        assert await _dlq_len(redis_client, stream) == 1
        assert guard_scans >= 3
        assert ack_failures == 1
        dlq_entries = await redis_client.xrange(dlq_stream)
        retained = [
            fields
            for _, fields in dlq_entries
            if fields.get("original_id") == original_id
        ]
        assert len(retained) == 1
    finally:
        await consumer.stop()
        await redis_client.delete(stream, dlq_stream)


@pytest.mark.asyncio
async def test_reclaimed_work_is_heartbeat_protected(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entries claimed by the reclaimer stay protected while reprocessed.

    XAUTOCLAIM resets a claimed entry's idle time, but slow reprocessing
    (guard scan + requeue of up to `count` entries) would let the idle
    counter cross the threshold again, letting another instance steal and
    duplicate the entry mid-reclaim. The heartbeat must refresh claimed
    entries too, keeping their idle time below the threshold.
    """
    stream = f"test_recovery_reclaim_protected:{uuid4()}"
    group = f"group-reclaim-protected-{uuid4()}"
    consumer_name = f"consumer-reclaim-prot-{uuid4()}"
    delivered: list[str] = []
    handler_called = asyncio.Event()

    async def handler(message: TestRecoveryMessage) -> None:
        delivered.append(message.content)
        handler_called.set()

    consumer = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=consumer_name,
        block_ms=10,
        reclaim_idle_ms=100,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    original_id = await _add_entry(redis_client, stream, "reclaim-protected")
    await _deliver_to_dead_consumer(redis_client, stream, group)
    assert await _pending_count(redis_client, stream, group) == 1

    original_reclaim_entry = consumer._reclaim_entry

    async def delayed_reclaim_entry(redis: Redis, entry_id: Any, fields: dict) -> None:
        await asyncio.sleep(1.5)
        await original_reclaim_entry(redis, entry_id, fields)

    monkeypatch.setattr(consumer, "_reclaim_entry", delayed_reclaim_entry)

    await consumer.start()
    try:
        saw_claimed = False
        deadline = monotonic() + 10
        while monotonic() < deadline:
            pending_entries = await redis_client.xpending_range(
                stream, group, "-", "+", 10
            )
            claimed = [
                entry for entry in pending_entries if entry["consumer"] == consumer_name
            ]
            for entry in claimed:
                saw_claimed = True
                assert entry["time_since_delivered"] < 100, (
                    f"claimed entry idle {entry['time_since_delivered']}ms exceeds "
                    "the reclaim threshold while being reprocessed"
                )
            if not pending_entries and saw_claimed:
                break
            await asyncio.sleep(0.03)
        assert saw_claimed, "reclaimer never claimed the abandoned entry"

        entries = await redis_client.xrange(stream)
        assert len(entries) == 2
        copies = [
            fields for _, fields in entries if fields.get("original_id") == original_id
        ]
        assert len(copies) == 1
        assert delivered == ["reclaim-protected"]
        assert await _dlq_len(redis_client, stream) == 0
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_heartbeat_covers_batch_delivered_during_shutdown_read(
    redis_client: Redis,
) -> None:
    """A batch delivered by a blocked read after stop() stays protected.

    stop() sets the shared stop event while the main loop can still be
    blocked inside XREADGROUP with empty in-flight sets. If the heartbeat
    honored the stop event as soon as the sets were empty, a message
    arriving before the read times out would be processed unprotected and
    another instance's reclaimer could requeue it mid-handler: a duplicate
    delivery during a clean shutdown. The heartbeat must stay alive until
    the worker tasks themselves are done.
    """
    stream = f"test_recovery_shutdown_read:{uuid4()}"
    group = f"group-shutdown-read-{uuid4()}"
    calls: list[str] = []
    handler_started = asyncio.Event()

    async def handler_a(message: TestRecoveryMessage) -> None:
        calls.append("a")
        handler_started.set()
        await asyncio.sleep(2.5)

    async def handler_b(message: TestRecoveryMessage) -> None:
        calls.append("b")

    consumer_a = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler_a,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-read-a-{uuid4()}",
        block_ms=5000,
        reclaim_idle_ms=100,
    )
    consumer_b = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler_b,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-read-b-{uuid4()}",
        block_ms=10,
        reclaim_idle_ms=100,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)

    await consumer_a.start()
    try:
        # A is now blocked inside XREADGROUP on an empty stream.
        await asyncio.sleep(0.1)
        stopping = asyncio.create_task(consumer_a.stop())
        await asyncio.sleep(0.1)
        assert consumer_a._heartbeat_task is not None
        assert not consumer_a._heartbeat_task.done(), (
            "heartbeat exited while the main loop can still receive a batch"
        )

        await _add_entry(redis_client, stream, "late")
        await asyncio.wait_for(handler_started.wait(), timeout=5)
        await consumer_b.start()
        try:
            # Blocks until A has drained the late batch (~2.5s): B's
            # reclaimer polls several times inside that window.
            await stopping
            assert calls == ["a"]
            assert await redis_client.xlen(stream) == 1
            assert await _pending_count(redis_client, stream, group) == 0
            assert await _dlq_len(redis_client, stream) == 0
        finally:
            await consumer_b.stop()
    finally:
        await consumer_a.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_malformed_retries_routes_to_dlq_and_batch_continues(
    redis_client: Redis,
) -> None:
    """An unreadable retries field goes to DLQ without stranding siblings.

    A malformed retries field cannot be counted nor requeued: before the
    fix it escaped _reclaim_entry, aborted the claimed batch and left the
    healthy sibling claimed-but-never-processed, reclaimed forever. The
    malformed entry must be retained in DLQ (idempotently, acked after
    confirmed retention) and the healthy sibling must be requeued normally.
    """
    stream = f"test_recovery_malformed:{uuid4()}"
    group = f"group-malformed-{uuid4()}"
    delivered: list[str] = []

    async def handler(message: TestRecoveryMessage) -> None:
        delivered.append(message.content)

    consumer = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=f"consumer-malformed-{uuid4()}",
        block_ms=10,
        reclaim_idle_ms=100,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    bad_id = await redis_client.xadd(
        stream, {"data": json.dumps({"content": "poison"}), "retries": "bad"}
    )
    good_id = await _add_entry(redis_client, stream, "healthy")
    await _deliver_to_dead_consumer(redis_client, stream, group)
    assert await _pending_count(redis_client, stream, group) == 2

    await consumer.start()
    try:

        async def _dlq_has(entry_id: str) -> bool:
            entries = await redis_client.xrange(f"{stream}:dlq")
            return any(fields.get("original_id") == entry_id for _, fields in entries)

        async def _copy_exists(entry_id: str) -> bool:
            entries = await redis_client.xrange(stream)
            return any(fields.get("original_id") == entry_id for _, fields in entries)

        await _wait_until(lambda: _dlq_has(str(bad_id)), timeout=5)
        await _wait_until(lambda: _copy_exists(str(good_id)), timeout=5)
        await _wait_until(lambda: delivered == ["healthy"], timeout=5)
        await _wait_until(_pending_is_zero_pred(redis_client, stream, group), timeout=5)
        assert consumer._reclaiming_ids == set()
        assert consumer._reclaimer_task is not None
        assert not consumer._reclaimer_task.done()
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_reclaiming_ids_cleared_when_reclaim_batch_is_cancelled(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling the reclaimer mid-batch must not strand unvisited entries.

    stop() cancels the reclaimer through wait_for on timeout, and any
    escaping exception aborts the claimed-batch loop. Both must clean the
    whole batch's IDs from _reclaiming_ids: a stale ID would be refreshed
    by the heartbeat forever, making the entry unrecoverable by this
    instance or any other.
    """
    stream = f"test_reclaim_cancel:{uuid4()}"
    group = f"group-reclaim-cancel-{uuid4()}"
    consumer_name = f"consumer-cancel-{uuid4()}"
    first_entry_started = asyncio.Event()

    async def handler(message: TestRecoveryMessage) -> None:
        pass

    consumer = SimpleStreamConsumer[TestRecoveryMessage](
        stream_name=stream,
        handler=handler,
        message_class=TestRecoveryMessage,
        consumer_group=group,
        consumer_name=consumer_name,
        block_ms=10,
        reclaim_idle_ms=100,
    )

    async def slow_reclaim_entry(redis: Redis, entry_id: Any, fields: dict) -> None:
        first_entry_started.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(consumer, "_reclaim_entry", slow_reclaim_entry)

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    for _ in range(2):
        await _add_entry(redis_client, stream, "claimed")
    await _deliver_to_dead_consumer(redis_client, stream, group)
    assert await _pending_count(redis_client, stream, group) == 2

    consumer._reclaimer_task = asyncio.create_task(consumer._reclaim_pending_messages())
    consumer._heartbeat_task = asyncio.create_task(
        consumer._heartbeat_in_flight_entries()
    )
    try:
        await asyncio.wait_for(first_entry_started.wait(), timeout=5)
        # Both claimed IDs are registered; the first is being processed.
        assert len(consumer._reclaiming_ids) == 2

        consumer._reclaimer_task.cancel()
        await asyncio.gather(consumer._reclaimer_task, return_exceptions=True)
        assert consumer._reclaiming_ids == set(), (
            "cancelled reclaim batch left unvisited entries heartbeat-protected"
        )

        consumer._heartbeat_task.cancel()
        await asyncio.gather(consumer._heartbeat_task, return_exceptions=True)
    finally:
        consumer._reclaimer_task = None
        consumer._heartbeat_task = None
        await redis_client.delete(stream, f"{stream}:dlq")
