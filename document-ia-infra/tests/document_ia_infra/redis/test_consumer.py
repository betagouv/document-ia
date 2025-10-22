import asyncio
import json
import logging
from typing import Any

import pytest

from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.redis.consumer import Consumer
from document_ia_infra.redis.serializable_message import SerializableMessage


class SampleMessage(SerializableMessage):
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def to_dict(self) -> dict[str, Any]:
        return self.payload

    @staticmethod
    def from_json(data: str) -> "SampleMessage":
        # raises ValueError if data is not valid JSON
        return SampleMessage(json.loads(data))


class MockRedis:
    def __init__(self, stream_name: str):
        self.stream_name = stream_name
        self._xread_batches: list[list[tuple[str, dict[str, Any]]]] = []
        self._xread_calls = 0
        self.acks: list[tuple[str, str]] = []  # (stream, msg_id)
        self.xadd_calls: list[tuple[str, dict[str, Any]]] = []  # (stream, fields)
        self.groups_created: set[tuple[str, str]] = set()
        self._xautoclaim_queue: list[tuple[str, list[tuple[str, dict[str, Any]]], list[str]]] = []
        self.closed = False

    def queue_xread_batch(self, entries: list[tuple[str, dict[str, Any]]]):
        self._xread_batches.append(entries)

    def queue_xautoclaim(self, next_start: str, claimed: list[tuple[str, dict[str, Any]]]):
        self._xautoclaim_queue.append((next_start, claimed, []))

    async def ping(self):
        return True

    async def close(self):
        self.closed = True

    async def xgroup_create(self, name: str, groupname: str, id: str, mkstream: bool):
        self.groups_created.add((name, groupname))
        return True

    async def xreadgroup(self, group: str, consumer: str, streams: dict[str, str], count: int, block: int):
        self._xread_calls += 1
        # returns a batch if available, otherwise an empty list
        if self._xread_batches:
            entries = self._xread_batches.pop(0)
            return [(self.stream_name, entries)]
        # no new message
        # simulate blocking by sleeping briefly
        await asyncio.sleep(0.01)
        return []

    async def xack(self, stream: str, group: str, msg_id: str):
        self.acks.append((stream, msg_id))
        return 1

    async def xadd(self, stream: str, fields: dict[str, Any]):
        self.xadd_calls.append((stream, dict(fields)))
        return "0-1"

    async def xautoclaim(self, stream: str, group: str, consumer: str, min_idle_ms: int, start: str, count: int):
        if self._xautoclaim_queue:
            return self._xautoclaim_queue.pop(0)
        await asyncio.sleep(0.01)
        return (start, [], [])


@pytest.mark.asyncio
async def test_consumer_happy_path(monkeypatch):
    stream = "test-stream"
    group = "g1"
    consumer_name = "c1"

    # Prepare a valid message
    payload = {"a": 1}
    data = json.dumps(payload)
    msg_id = "1700000000000-0"

    mock_redis = MockRedis(stream)
    mock_redis.queue_xread_batch([(msg_id, {"data": data, "retries": "0"})])

    # Patch Redis connection
    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module
    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    processed = asyncio.Event()

    async def process_ok(msg: SampleMessage, rc: int, _is_last: bool):
        assert msg.payload == payload
        assert rc == 0
        processed.set()

    c = Consumer[SampleMessage](
        consumer_name=consumer_name,
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=process_ok,
        worker_number=1,
        max_retry_number=3,
    )

    # Start listener task, then stop after processing
    task = asyncio.create_task(c._start_listening_messages())
    await asyncio.wait_for(processed.wait(), timeout=2)
    c.stop_flag.set()
    await asyncio.wait_for(task, timeout=2)

    # Assertions
    assert mock_redis.acks == [(stream, msg_id)]
    # no xadd (neither requeue nor DLQ)
    assert mock_redis.xadd_calls == []


@pytest.mark.asyncio
async def test_consumer_retryable_error_requeues(monkeypatch):
    stream = "test-stream"
    group = "g1"
    consumer_name = "c1"

    payload = {"a": 1}
    data = json.dumps(payload)
    msg_id = "1700000000000-0"

    mock_redis = MockRedis(stream)
    mock_redis.queue_xread_batch([(msg_id, {"data": data, "retries": "0"})])

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module
    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    async def process_retry(msg: SampleMessage, rc: int, _is_last: bool):
        raise RetryableException("temporary")

    c = Consumer[SampleMessage](
        consumer_name=consumer_name,
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=process_retry,
        worker_number=1,
        max_retry_number=3,
    )

    task = asyncio.create_task(c._start_listening_messages())
    # wait for an ack to happen
    for _ in range(100):
        if mock_redis.acks:
            break
        await asyncio.sleep(0.02)
    c.stop_flag.set()
    await asyncio.wait_for(task, timeout=2)

    # Should have requeued with retries=1 and ack
    assert (stream, msg_id) in mock_redis.acks
    assert any(call[0] == stream and call[1].get("retries") == "1" for call in mock_redis.xadd_calls)


@pytest.mark.asyncio
async def test_consumer_not_retryable_goes_to_dlq(monkeypatch):
    stream = "test-stream"
    group = "g1"
    consumer_name = "c1"

    payload = {"a": 1}
    data = json.dumps(payload)
    msg_id = "1700000000000-0"

    mock_redis = MockRedis(stream)
    mock_redis.queue_xread_batch([(msg_id, {"data": data, "retries": "0"})])

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module
    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    async def process_fail(msg: SampleMessage, rc: int, _is_last: bool):
        raise RuntimeError("boom")

    c = Consumer[SampleMessage](
        consumer_name=consumer_name,
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=process_fail,
        worker_number=1,
        max_retry_number=3,
    )

    task = asyncio.create_task(c._start_listening_messages())
    # wait for ack
    for _ in range(100):
        if mock_redis.acks:
            break
        await asyncio.sleep(0.02)
    c.stop_flag.set()
    await asyncio.wait_for(task, timeout=2)

    # Ack and DLQ send: stream ':dlq'
    assert (stream, msg_id) in mock_redis.acks
    assert any(call[0] == f"{stream}:dlq" for call in mock_redis.xadd_calls)


@pytest.mark.asyncio
async def test_consumer_decode_error_goes_to_dlq(monkeypatch):
    stream = "test-stream"
    group = "g1"
    consumer_name = "c1"

    # non-JSON data => from_json raises ValueError
    data = "{invalid-json}"
    msg_id = "1700000000000-0"

    mock_redis = MockRedis(stream)
    mock_redis.queue_xread_batch([(msg_id, {"data": data, "retries": "0"})])

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module
    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    async def process_noop(msg: SampleMessage, rc: int, _is_last: bool):
        pass

    c = Consumer[SampleMessage](
        consumer_name=consumer_name,
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=process_noop,
        worker_number=1,
        max_retry_number=3,
    )

    task = asyncio.create_task(c._start_listening_messages())
    for _ in range(100):
        if mock_redis.acks:
            break
        await asyncio.sleep(0.02)
    c.stop_flag.set()
    await asyncio.wait_for(task, timeout=2)

    # Ack and DLQ (decode_error)
    assert (stream, msg_id) in mock_redis.acks
    assert any(call[0] == f"{stream}:dlq" for call in mock_redis.xadd_calls)


@pytest.mark.asyncio
async def test_reclaimer_requeues_or_dlq(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    stream = "test-stream"
    group = "g1"
    consumer_name = "c1"

    mock_redis = MockRedis(stream)

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module
    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    c = Consumer[SampleMessage](
        consumer_name=consumer_name,
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
        worker_number=1,
        max_retry_number=2,
    )

    # First message: retries=0 -> retry_count=1 -> fields['retries']=2 then xadd + ack
    msg1 = ("1700000000000-0", {"data": json.dumps({"a": 1}), "retries": "0"})
    # Second message: retries=2 -> retry_count=3 > max -> DLQ
    msg2 = ("1700000000001-0", {"data": json.dumps({"a": 2}), "retries": "2"})

    mock_redis.queue_xautoclaim("0-1", [msg1, msg2])

    # start reclaimer and stop after one pass
    task = asyncio.create_task(c._reclaim_pending_messages())
    await asyncio.sleep(0.1)
    c.stop_flag.set()
    await asyncio.wait_for(task, timeout=2)

    # Verify we have xadd (requeue) for msg1 and DLQ for msg2
    requeues = [call for call in mock_redis.xadd_calls if call[0] == stream]
    dlqs = [call for call in mock_redis.xadd_calls if call[0] == f"{stream}:dlq"]

    assert any(call[1].get("data") for call in requeues)
    assert any(call[1].get("reason") == "max_retries_exceeded" for call in dlqs)


@pytest.mark.asyncio
async def test_ack_failure_does_not_crash_or_dlq(monkeypatch):
    stream = "test-stream"
    group = "g1"
    consumer_name = "c1"

    data = json.dumps({"ok": True})
    msg_id = "1700000000000-0"

    mock_redis = MockRedis(stream)
    mock_redis.queue_xread_batch([(msg_id, {"data": data, "retries": "0"})])

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module
    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    # Force xack failure
    async def failing_xack(stream_name: str, group_name: str, mid: str):
        raise RuntimeError("ack failed")

    mock_redis.xack = failing_xack  # type: ignore

    async def process_ok(msg: SampleMessage, rc: int, _is_last: bool):
        return None

    c = Consumer[SampleMessage](
        consumer_name=consumer_name,
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=process_ok,
        worker_number=1,
        max_retry_number=3,
    )

    task = asyncio.create_task(c._start_listening_messages())
    # let it run briefly
    await asyncio.sleep(0.05)
    c.stop_flag.set()
    await asyncio.wait_for(task, timeout=2)

    # No DLQ despite ACK failure
    assert all(call[0] != f"{stream}:dlq" for call in mock_redis.xadd_calls)


@pytest.mark.asyncio
async def test_requeue_failure_sends_to_dlq_and_ack(monkeypatch):
    stream = "test-stream"
    group = "g1"
    consumer_name = "c1"

    data = json.dumps({"need": "retry"})
    msg_id = "1700000000000-0"

    mock_redis = MockRedis(stream)
    mock_redis.queue_xread_batch([(msg_id, {"data": data, "retries": "0"})])

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module
    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    async def process_retry(_msg: SampleMessage, _rc: int, _is_last: bool):
        raise RetryableException("temp")

    # Monkeypatch xadd to fail on requeue but succeed for DLQ
    original_xadd = mock_redis.xadd

    async def conditional_xadd(stream_name: str, fields: dict[str, Any]):
        if stream_name == stream:
            raise RuntimeError("xadd requeue failed")
        return await original_xadd(stream_name, fields)  # type: ignore

    mock_redis.xadd = conditional_xadd  # type: ignore

    c = Consumer[SampleMessage](
        consumer_name=consumer_name,
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=process_retry,
        worker_number=1,
        max_retry_number=3,
    )

    task = asyncio.create_task(c._start_listening_messages())
    # wait until ACK is attempted
    await asyncio.sleep(0.1)
    c.stop_flag.set()
    await asyncio.wait_for(task, timeout=2)

    # Should have sent to DLQ with reason=error_requeueing_message
    assert any(
        call[0] == f"{stream}:dlq" and call[1].get("reason") == "error_requeueing_message"
        for call in mock_redis.xadd_calls
    )


@pytest.mark.asyncio
async def test_init_creates_consumer_group(monkeypatch):
    stream = "test-stream"
    group = "g1"
    consumer_name = "c1"

    mock_redis = MockRedis(stream)

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module
    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    c = Consumer[SampleMessage](
        consumer_name=consumer_name,
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _ : asyncio.sleep(0),
    )

    await c._init_consumer()
    assert (stream, group) in mock_redis.groups_created
    await c._de_init_consumer()


@pytest.mark.asyncio
async def test_no_message_loop_and_stop(monkeypatch):
    stream = "test-stream"
    group = "g1"
    consumer_name = "c1"

    mock_redis = MockRedis(stream)

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module
    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    async def process_noop(msg: SampleMessage, rc: int, _is_last: bool):
        return None

    c = Consumer[SampleMessage](
        consumer_name=consumer_name,
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=process_noop,
    )

    # stop shortly after start
    task = asyncio.create_task(c._start_listening_messages())
    await asyncio.sleep(0.05)
    c.stop_flag.set()
    await asyncio.wait_for(task, timeout=2)

    # no activity
    assert mock_redis.acks == []
    assert mock_redis.xadd_calls == []


@pytest.mark.asyncio
async def test_shutdown_waits_for_inflight_processing(monkeypatch):
    """When stop_flag is set while a processing is in progress,
    the consumer must wait for the processing to finish (ACK done) and then stop gracefully."""
    import threading

    stream = "test-stream"
    group = "g1"
    consumer_name = "c1"

    payload = {"slow": True}
    data = json.dumps(payload)
    msg_id = "1700000000000-0"

    mock_redis = MockRedis(stream)
    mock_redis.queue_xread_batch([(msg_id, {"data": data, "retries": "0"})])

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module
    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    started_evt = threading.Event()

    async def process_slow(msg: SampleMessage, rc: int, _is_last: bool):
        # signal processing start
        started_evt.set()
        # simulate a long processing
        await asyncio.sleep(0.2)

    c = Consumer[SampleMessage](
        consumer_name=consumer_name,
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=process_slow,
        worker_number=1,
        max_retry_number=3,
    )

    task = asyncio.create_task(c._start_listening_messages())

    # Wait until the processing has actually started
    for _ in range(100):
        if started_evt.is_set():
            break
        await asyncio.sleep(0.01)
    assert started_evt.is_set(), "Processing did not start within the expected time"

    # Trigger stop during processing
    c.stop_flag.set()

    # Wait for the consumer to stop (it must wait for the current processing to finish)
    await asyncio.wait_for(task, timeout=3)

    # Verify that ACK has been performed and that no new batch was read
    assert mock_redis.acks == [(stream, msg_id)]
    assert mock_redis._xread_calls == 1
