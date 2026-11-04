"""Integration tests for API webhook Consumer crash recovery (issue #112).

Covers recovery of entries left pending by a stopped or crashed API instance
using the unified Consumer from document_ia_infra:
- XAUTOCLAIM-based reclaim by a live instance
- Per-instance consumer identities observable in XINFO CONSUMERS
- Idempotent requeue and DLQ retention when XACK fails
- Fail-closed behavior when stream/DLQ XRANGE guards fail
- Heartbeat protection of in-flight batches, reclaimed work, shutdown drain,
  and late batches delivered during blocked shutdown reads
- start_from ('0-0' vs '$') group initialization
- Poison/malformed retries isolation and cancelled reclaim batch cleanup
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from time import monotonic
from typing import Any, Awaitable, Callable
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from document_ia_infra.redis.consumer import (
    AsyncIoConsumer,
    build_instance_consumer_name,
)
from document_ia_infra.redis.serializable_message import SerializableMessage


@dataclass
class SampleRecoveryMessage(SerializableMessage):
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"content": self.content}

    @staticmethod
    def from_json(data: str) -> "SampleRecoveryMessage":
        payload = json.loads(data)
        return SampleRecoveryMessage(content=payload["content"])


def _build_consumer(
    *,
    stream_name: str,
    consumer_group: str,
    consumer_name: str,
    handler: Callable[[SampleRecoveryMessage, int, bool], Awaitable[None]],
    block_time: int = 10,
    batch_size: int = 50,
    max_retry_number: int = 4,
    reclaim_idle_ms: int = 200,
    start_from: str = "0-0",
) -> AsyncIoConsumer[SampleRecoveryMessage]:
    return AsyncIoConsumer[SampleRecoveryMessage](
        consumer_name=consumer_name,
        consumer_group=consumer_group,
        stream_name=stream_name,
        batch_size=batch_size,
        block_time=block_time,
        message_class=SampleRecoveryMessage,
        process_message_callable=handler,
        max_retry_number=max_retry_number,
        max_concurrency=10,
        start_from=start_from,
        reclaim_idle_ms=reclaim_idle_ms,
    )


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
    response = await redis.xreadgroup(
        group, consumer, streams={stream: ">"}, count=10, block=10
    )
    assert response, "dead consumer should have received the entry"


@pytest.fixture(autouse=True)
def mock_api_key_service_auth() -> None:
    """Recovery tests do not exercise API authentication or PostgreSQL."""


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


@pytest.mark.asyncio
async def test_reclaimer_recovers_entry_of_dead_instance(
    redis_client: Redis,
) -> None:
    stream = f"test_recovery_dead_instance:{uuid4()}"
    group = f"group-recovery-dead-{uuid4()}"
    handler_called = asyncio.Event()
    delivered: list[str] = []

    async def handler(message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        delivered.append(message.content)
        handler_called.set()

    consumer = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=f"consumer-live-{uuid4()}",
        handler=handler,
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
    stream = f"test_recovery_in_flight:{uuid4()}"
    group = f"group-in-flight-{uuid4()}"
    calls: list[str] = []
    all_done = asyncio.Event()

    async def handler(message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        calls.append(message.content)
        if message.content == "slow-first":
            await asyncio.sleep(1.4)
        if len(calls) >= 2 and "slow-first" in calls and "fast-second" in calls:
            if message.content == "slow-first":
                all_done.set()

    consumer = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=f"consumer-in-flight-{uuid4()}",
        handler=handler,
        reclaim_idle_ms=250,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    await _add_entry(redis_client, stream, "slow-first")
    await _add_entry(redis_client, stream, "fast-second")

    await consumer.start()
    try:
        await asyncio.wait_for(all_done.wait(), timeout=10)
        await asyncio.sleep(1.5)
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
    stream = f"test_recovery_requeue_idem:{uuid4()}"
    group = f"group-requeue-idem-{uuid4()}"
    delivered: list[str] = []
    handler_called = asyncio.Event()

    async def handler(message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        delivered.append(message.content)
        handler_called.set()

    consumer = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=f"consumer-requeue-idem-{uuid4()}",
        handler=handler,
        reclaim_idle_ms=100,
        max_retry_number=4,
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
async def test_live_instance_recovers_entry_abandoned_by_crashed_instance(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si une instance A lit une entrée et crashe avant traitement/ACK, une
    seconde instance B l'identifie via XAUTOCLAIM, la remet en file et les deux
    identités distinctes sont visibles dans XINFO CONSUMERS."""
    stream = f"test_recovery_two_instances:{uuid4()}"
    group = f"group-two-instances-{uuid4()}"
    calls: list[tuple[str, str]] = []
    a_cancelled = asyncio.Event()
    success = asyncio.Event()

    async def handler_a(_message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        calls.append(("a", "crashed"))
        a_cancelled.set()
        raise asyncio.CancelledError()

    async def handler_b(_message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        calls.append(("b", "success"))
        success.set()

    name_a = build_instance_consumer_name("api-webhook-consumer-a")
    name_b = build_instance_consumer_name("api-webhook-consumer-b")
    assert name_a != name_b

    consumer_a = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=name_a,
        handler=handler_a,
        reclaim_idle_ms=10_000,
    )
    consumer_b = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=name_b,
        handler=handler_b,
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
        await asyncio.wait_for(a_cancelled.wait(), timeout=5)
        await consumer_a.stop()
        assert await _pending_count(redis_client, stream, group) == 1

        await consumer_b.start()
        try:
            await asyncio.wait_for(success.wait(), timeout=10)
            await _wait_until(
                _pending_is_zero_pred(redis_client, stream, group), timeout=10
            )
            assert calls == [("a", "crashed"), ("b", "success")]
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
    stream = f"test_recovery_exhausted:{uuid4()}"
    group = f"group-exhausted-{uuid4()}"
    handler_called = asyncio.Event()

    async def handler(_message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        handler_called.set()

    consumer = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=f"consumer-exhausted-{uuid4()}",
        handler=handler,
        reclaim_idle_ms=100,
        max_retry_number=3,
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
    stream = f"test_recovery_no_resend:{uuid4()}"
    group = f"group-no-resend-{uuid4()}"
    delivered: list[str] = []
    handler_called = asyncio.Event()

    async def handler(message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        delivered.append(message.content)
        handler_called.set()

    consumer = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=f"consumer-no-resend-{uuid4()}",
        handler=handler,
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
        await asyncio.sleep(1.5)
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
    stream = f"test_recovery_start_dollar:{uuid4()}"
    group = f"group-start-dollar-{uuid4()}"
    handler_called = asyncio.Event()

    async def handler(_message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        handler_called.set()

    entry_id = await _add_entry(redis_client, stream, "history")

    consumer = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=f"consumer-start-dollar-{uuid4()}",
        handler=handler,
        start_from="$",
    )

    await consumer.start()
    try:
        await asyncio.sleep(0.5)
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
    stream = f"test_recovery_start_zero:{uuid4()}"
    group = f"group-start-zero-{uuid4()}"
    delivered: list[str] = []
    handler_called = asyncio.Event()

    async def handler(message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        delivered.append(message.content)
        handler_called.set()

    await _add_entry(redis_client, stream, "history")

    consumer = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=f"consumer-start-zero-{uuid4()}",
        handler=handler,
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
    stream = f"test_recovery_shutdown_drain:{uuid4()}"
    group = f"group-shutdown-drain-{uuid4()}"
    calls: list[str] = []
    handler_started = asyncio.Event()

    async def handler_a(_message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        calls.append("a")
        handler_started.set()
        await asyncio.sleep(1.5)

    async def handler_b(_message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        calls.append("b")

    consumer_a = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=f"consumer-drain-a-{uuid4()}",
        handler=handler_a,
        reclaim_idle_ms=250,
    )
    consumer_b = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=f"consumer-drain-b-{uuid4()}",
        handler=handler_b,
        reclaim_idle_ms=250,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    await _add_entry(redis_client, stream, "draining")

    await consumer_a.start()
    try:
        await asyncio.wait_for(handler_started.wait(), timeout=5)
        await consumer_b.start()
        try:
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
    stream = f"test_recovery_guard_fail_closed:{uuid4()}"
    group = f"group-guard-fail-closed-{uuid4()}"
    delivered: list[str] = []
    handler_called = asyncio.Event()

    async def handler(message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        delivered.append(message.content)
        handler_called.set()

    consumer = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=f"consumer-guard-fail-{uuid4()}",
        handler=handler,
        reclaim_idle_ms=100,
        max_retry_number=4,
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
    original_eval = redis_client.eval
    guard_scans = 0

    async def fail_second_guard_scan(*args: Any, **kwargs: Any) -> Any:
        nonlocal guard_scans
        if args and args[0] == stream and "min" in kwargs:
            guard_scans += 1
            if guard_scans == 2:
                raise ConnectionError("redis scan failed")
        return await original_xrange(*args, **kwargs)

    async def fail_second_guard_eval(script: str, numkeys: int, *args: Any) -> Any:
        nonlocal guard_scans
        if numkeys == 1 and args and args[0] == stream:
            guard_scans += 1
            if guard_scans == 2:
                raise ConnectionError("redis scan failed")
        return await original_eval(script, numkeys, *args)

    monkeypatch.setattr(redis_client, "xack", fail_ack_once_for_original)
    monkeypatch.setattr(redis_client, "xrange", fail_second_guard_scan)
    monkeypatch.setattr(redis_client, "eval", fail_second_guard_eval)

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
    stream = f"test_recovery_dlq_guard_fail_closed:{uuid4()}"
    group = f"group-dlq-guard-fail-closed-{uuid4()}"
    dlq_stream = f"{stream}:dlq"

    async def handler(_message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        pass

    consumer = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=f"consumer-dlq-guard-fail-{uuid4()}",
        handler=handler,
        reclaim_idle_ms=100,
        max_retry_number=3,
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
    original_eval = redis_client.eval
    guard_scans = 0

    async def fail_second_dlq_guard_scan(*args: Any, **kwargs: Any) -> Any:
        nonlocal guard_scans
        if args and args[0] == dlq_stream and "min" in kwargs:
            guard_scans += 1
            if guard_scans == 2:
                raise ConnectionError("redis scan failed")
        return await original_xrange(*args, **kwargs)

    async def fail_second_dlq_guard_eval(script: str, numkeys: int, *args: Any) -> Any:
        nonlocal guard_scans
        if numkeys == 1 and args and args[0] == dlq_stream:
            guard_scans += 1
            if guard_scans == 2:
                raise ConnectionError("redis scan failed")
        return await original_eval(script, numkeys, *args)

    monkeypatch.setattr(redis_client, "xack", fail_ack_once_for_original)
    monkeypatch.setattr(redis_client, "xrange", fail_second_dlq_guard_scan)
    monkeypatch.setattr(redis_client, "eval", fail_second_dlq_guard_eval)

    await consumer.start()
    try:
        await _wait_until(_dlq_len_is_pred(redis_client, stream, 1), timeout=10)
        assert await _pending_count(redis_client, stream, group) == 1

        await _wait_until(lambda: guard_scans >= 2, timeout=10)
        assert await _dlq_len(redis_client, stream) == 1
        assert await _pending_count(redis_client, stream, group) == 1

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
async def test_malformed_retries_routes_to_dlq_and_batch_continues(
    redis_client: Redis,
) -> None:
    stream = f"test_recovery_malformed:{uuid4()}"
    group = f"group-malformed-{uuid4()}"
    delivered: list[str] = []

    async def handler(message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        delivered.append(message.content)

    consumer = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=f"consumer-malformed-{uuid4()}",
        handler=handler,
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
        assert consumer.reclaimer_task is not None
        assert not consumer.reclaimer_task.done()
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_reclaiming_ids_cleared_when_reclaim_batch_is_cancelled(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = f"test_reclaim_cancel:{uuid4()}"
    group = f"group-reclaim-cancel-{uuid4()}"
    first_entry_started = asyncio.Event()

    async def handler(_message: SampleRecoveryMessage, _rc: int, _last: bool) -> None:
        pass

    consumer = _build_consumer(
        stream_name=stream,
        consumer_group=group,
        consumer_name=f"consumer-cancel-{uuid4()}",
        handler=handler,
        reclaim_idle_ms=200,
    )

    async def slow_reclaim_entry(
        _redis: Redis, _entry_id: str, _fields: dict[str, Any] | None
    ) -> None:
        first_entry_started.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(consumer, "_reclaim_entry", slow_reclaim_entry)

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    for _ in range(2):
        await _add_entry(redis_client, stream, "claimed")
    await _deliver_to_dead_consumer(redis_client, stream, group)
    assert await _pending_count(redis_client, stream, group) == 2

    consumer.reclaimer_task = asyncio.create_task(consumer._reclaim_pending_messages())
    consumer.heartbeat_task = asyncio.create_task(
        consumer._heartbeat_in_flight_entries()
    )
    try:
        await asyncio.wait_for(first_entry_started.wait(), timeout=5)
        assert len(consumer._reclaiming_ids) == 2

        consumer.reclaimer_task.cancel()
        await asyncio.gather(consumer.reclaimer_task, return_exceptions=True)
        assert consumer._reclaiming_ids == set()

        consumer.stop_flag.set()
        await asyncio.wait_for(consumer.heartbeat_task, timeout=2)
    finally:
        consumer.reclaimer_task = None
        consumer.heartbeat_task = None
        await redis_client.delete(stream, f"{stream}:dlq")
