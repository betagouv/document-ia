"""Integration tests for ProgressTracker, conditional heartbeat, watchdog, and execution lease."""

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from document_ia_infra.redis.asyncio_consumer import AsyncIoConsumer
from document_ia_infra.redis.progress_tracker import (
    ProgressTracker,
    get_current_progress_tracker,
    record_step_progress,
)
from document_ia_infra.redis.redis_manager import RedisManager
from document_ia_infra.redis.serializable_message import SerializableMessage
from document_ia_infra.redis.thread_consumer import ThreadConsumer


class ProgressTaskMessage(SerializableMessage):
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    @property
    def workflow_execution_id(self) -> str | None:
        return self.payload.get("workflow_execution_id")

    def to_dict(self) -> dict[str, Any]:
        return self.payload

    @staticmethod
    def from_json(data: str) -> "ProgressTaskMessage":
        return ProgressTaskMessage(json.loads(data))


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
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
async def stream(redis_client: Redis) -> AsyncIterator[str]:
    name = f"test-progress:{uuid4()}"
    try:
        yield name
    finally:
        await redis_client.delete(name, f"{name}:dlq")


async def wait_until(predicate: Any, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while True:
            result = predicate()
            if asyncio.iscoroutine(result):
                result = await result
            if result:
                break
            await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_active_workflow_exceeding_reclaim_timeout_is_not_reclaimed(
    redis_client: Redis, stream: str
):
    """1. Un traitement actif qui progresse n'est pas repris du seul fait du dépassement de reclaim_idle_ms."""
    group = f"group-{uuid4()}"
    exec_id = f"exec-{uuid4()}"

    msg_id = await redis_client.xadd(
        stream, {"data": json.dumps({"workflow_execution_id": exec_id})}
    )

    started_event = threading.Event()
    continue_event = threading.Event()

    async def long_healthy_handler(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        started_event.set()
        for i in range(3):
            await asyncio.sleep(0.1)
            record_step_progress(f"step_{i}")
        await asyncio.to_thread(continue_event.wait)

    rm = RedisManager()
    consumer = ThreadConsumer[ProgressTaskMessage](
        consumer_name=f"worker-{uuid4()}",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        drain_timeout_s=0.2,
        message_class=ProgressTaskMessage,
        process_message_callable=long_healthy_handler,
        reclaim_idle_ms=300,
        step_progress_timeout_s=1.0,
        max_processing_time_s=5.0,
        use_execution_lease=True,
        close_redis_on_stop=True,
        current_redis_manager=rm,
    )
    consumer._heartbeat_interval_s = 0.05

    await consumer.start()
    try:
        await wait_until(started_event.is_set, timeout=3.0)

        # Attendre plus longtemps que reclaim_idle_ms (300ms)
        await asyncio.sleep(0.5)

        # Toujours une seule entrée sur le stream (pas de réexécution)
        entries = await redis_client.xrange(stream)
        assert len(entries) == 1
        assert entries[0][0] == msg_id

        # Libérer le handler
        continue_event.set()

        await wait_until(
            lambda: len(consumer._in_flight_ids) == 0 and not consumer.has_running_handlers,
            timeout=3.0,
        )

        info = await redis_client.xpending(stream, group)
        assert (info["pending"] if isinstance(info, dict) else info.pending) == 0

    finally:
        continue_event.set()
        await consumer.stop()


@pytest.mark.asyncio
async def test_stalled_workflow_stops_heartbeat_and_requeues_with_retry_increment(
    redis_client: Redis, stream: str
):
    """2. Le renouvellement s'arrête si une étape bloque (> step_timeout), avec rejeu immédiat et retries++."""
    group = f"group-{uuid4()}"
    exec_id = f"exec-{uuid4()}"

    msg_id = await redis_client.xadd(
        stream, {"data": json.dumps({"workflow_execution_id": exec_id}), "retries": "0"}
    )

    started_event = threading.Event()

    async def stalled_step_handler(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        started_event.set()
        for _ in range(100):
            await asyncio.sleep(0.05)
            tracker = get_current_progress_tracker()
            if tracker and tracker.is_aborted:
                break

    rm = RedisManager()
    consumer = ThreadConsumer[ProgressTaskMessage](
        consumer_name=f"worker-{uuid4()}",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        drain_timeout_s=0.2,
        message_class=ProgressTaskMessage,
        process_message_callable=stalled_step_handler,
        reclaim_idle_ms=5000,
        step_progress_timeout_s=0.2,
        max_processing_time_s=5.0,
        max_retry_number=3,
        use_execution_lease=True,
        close_redis_on_stop=True,
        current_redis_manager=rm,
    )
    consumer._heartbeat_interval_s = 0.05

    await consumer.start()
    try:
        await wait_until(started_event.is_set, timeout=3.0)

        async def requeued_present() -> bool:
            entries = await redis_client.xrange(stream)
            return any(
                fields.get("retries") == "1" and fields.get("original_id") == msg_id
                for _, fields in entries
            )

        await wait_until(requeued_present, timeout=3.0)

        pel_entries = await redis_client.xpending_range(stream, group, min="-", max="+", count=10)
        pel_ids = [e["message_id"] if isinstance(e, dict) else e.message_id for e in pel_entries]
        assert msg_id not in pel_ids

    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_max_processing_time_exceeded_routes_to_dlq(
    redis_client: Redis, stream: str
):
    """3. Tout dépassement du temps max total route en DLQ si max retries atteint."""
    group = f"group-{uuid4()}"
    exec_id = f"exec-{uuid4()}"

    msg_id = await redis_client.xadd(
        stream, {"data": json.dumps({"workflow_execution_id": exec_id}), "retries": "2"}
    )

    started_event = threading.Event()

    async def endlessly_progressing_handler(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        started_event.set()
        while True:
            await asyncio.sleep(0.05)
            record_step_progress("minor_step")
            tracker = get_current_progress_tracker()
            if tracker and tracker.is_aborted:
                break

    rm = RedisManager()
    consumer = ThreadConsumer[ProgressTaskMessage](
        consumer_name=f"worker-{uuid4()}",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        drain_timeout_s=0.2,
        message_class=ProgressTaskMessage,
        process_message_callable=endlessly_progressing_handler,
        reclaim_idle_ms=5000,
        step_progress_timeout_s=1.0,
        max_processing_time_s=0.25,
        max_retry_number=3,
        use_execution_lease=True,
        close_redis_on_stop=True,
        current_redis_manager=rm,
    )
    consumer._heartbeat_interval_s = 0.05

    await consumer.start()
    try:
        await wait_until(started_event.is_set, timeout=3.0)

        dlq_stream = f"{stream}:dlq"

        async def dlq_entry_present() -> bool:
            entries = await redis_client.xrange(dlq_stream)
            return any(
                fields.get("original_id") == msg_id and fields.get("reason") == "workflow_timeout"
                for _, fields in entries
            )

        await wait_until(dlq_entry_present, timeout=3.0)

        pel_entries = await redis_client.xpending_range(stream, group, min="-", max="+", count=10)
        pel_ids = [e["message_id"] if isinstance(e, dict) else e.message_id for e in pel_entries]
        assert msg_id not in pel_ids

    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_concurrency_with_execution_lease_excludes_duplicate_execution(
    redis_client: Redis, stream: str
):
    """4. Concurrence inter-workers avec use_execution_lease=True : un seul worker actif à la fois."""
    group = f"group-{uuid4()}"
    exec_id = f"exec-{uuid4()}"

    await redis_client.xadd(
        stream, {"data": json.dumps({"workflow_execution_id": exec_id}), "retries": "0"}
    )

    worker1_started = threading.Event()
    worker1_hold = threading.Event()
    worker2_executed = threading.Event()

    async def handler_worker1(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        worker1_started.set()
        await asyncio.to_thread(worker1_hold.wait)

    async def handler_worker2(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        worker2_executed.set()

    rm1 = RedisManager()
    rm2 = RedisManager()
    worker1 = ThreadConsumer[ProgressTaskMessage](
        consumer_name=f"worker-1-{uuid4()}",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        drain_timeout_s=0.2,
        message_class=ProgressTaskMessage,
        process_message_callable=handler_worker1,
        use_execution_lease=True,
        close_redis_on_stop=True,
        current_redis_manager=rm1,
    )
    worker2 = ThreadConsumer[ProgressTaskMessage](
        consumer_name=f"worker-2-{uuid4()}",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        drain_timeout_s=0.2,
        message_class=ProgressTaskMessage,
        process_message_callable=handler_worker2,
        use_execution_lease=True,
        close_redis_on_stop=True,
        current_redis_manager=rm2,
    )

    await worker1.start()
    try:
        await wait_until(worker1_started.is_set, timeout=3.0)

        # Vérifier que le bail est bien possédé par worker1
        lease_key = f"lock:workflow_execution:{exec_id}"
        lease_val = await redis_client.get(lease_key)
        assert lease_val is not None
        assert worker1.consumer_name in lease_val

        # Ajouter un 2ème message avec le MÊME execution_id sur le stream
        await redis_client.xadd(
            stream, {"data": json.dumps({"workflow_execution_id": exec_id}), "retries": "0"}
        )

        await worker2.start()
        # Laisser le temps à worker2 de lire le message
        await asyncio.sleep(0.3)

        # Worker 2 n'a PAS exécuté le message car le bail était actif sur worker 1
        assert not worker2_executed.is_set()

        # Libérer worker 1
        worker1_hold.set()
        await wait_until(
            lambda: len(worker1._in_flight_ids) == 0 and not worker1.has_running_handlers,
            timeout=3.0,
        )

        # Le bail est maintenant libéré
        async def lease_is_none() -> bool:
            return await redis_client.get(lease_key) is None

        await wait_until(lease_is_none, timeout=3.0)

    finally:
        worker1_hold.set()
        await worker1.stop()
        await worker2.stop()


@pytest.mark.asyncio
async def test_api_mode_without_steps(
    redis_client: Redis, stream: str
):
    """5. Mode API (AsyncIoConsumer, step_progress_timeout_s=None, use_execution_lease=False)."""
    group = f"group-{uuid4()}"
    webhook_id = f"wh-{uuid4()}"

    await redis_client.xadd(
        stream, {"data": json.dumps({"webhook_id": webhook_id}), "retries": "0"}
    )

    executed = asyncio.Event()

    async def api_webhook_handler(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        tracker = get_current_progress_tracker()
        assert tracker is not None
        assert tracker.step_progress_timeout_s is None
        assert tracker.max_processing_time_s == 15.0
        assert tracker.is_healthy()
        executed.set()

    rm = RedisManager()
    api_consumer = AsyncIoConsumer[ProgressTaskMessage](
        consumer_name=f"api-worker-{uuid4()}",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        drain_timeout_s=0.2,
        message_class=ProgressTaskMessage,
        process_message_callable=api_webhook_handler,
        max_processing_time_s=15.0,
        step_progress_timeout_s=None,
        use_execution_lease=False,
        close_redis_on_stop=True,
        current_redis_manager=rm,
    )

    await api_consumer.start()
    try:
        await asyncio.wait_for(executed.wait(), timeout=3.0)
        await wait_until(lambda: len(api_consumer._in_flight_ids) == 0, timeout=3.0)
        info = await redis_client.xpending(stream, group)
        assert (info["pending"] if isinstance(info, dict) else info.pending) == 0
    finally:
        await api_consumer.stop()
