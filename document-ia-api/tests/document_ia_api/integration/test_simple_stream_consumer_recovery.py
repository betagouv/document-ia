"""Integration tests for SimpleStreamConsumer crash recovery (issue #112).

Covers the recovery of entries left pending by a stopped or crashed API
instance: XAUTOCLAIM-based reclaim by a live instance, per-instance
consumer identities, idempotent DLQ retention for exhausted entries, no
requeue of successfully delivered entries, and start_from handling at
group creation.
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
