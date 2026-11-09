"""Integration tests for ProgressTracker, conditional heartbeat, watchdog, and execution lease."""

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from document_ia_infra.redis.asyncio_consumer import AsyncIoConsumer
from document_ia_infra.redis.base_consumer import InFlightContext
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


@pytest.fixture(autouse=True)
def configure_redis_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    from document_ia_infra.redis.redis_settings import redis_settings

    monkeypatch.setattr(redis_settings, "REDIS_URL", "redis://localhost:6379/0")


class LocalRedisManager(RedisManager):
    def __init__(self, client: Redis) -> None:
        super().__init__()
        self.redis = client

    async def get_connection(self) -> Redis:
        return self.redis

    async def close(self) -> None:
        pass


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

    rm = LocalRedisManager(redis_client)
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

    rm = LocalRedisManager(redis_client)
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

    rm = LocalRedisManager(redis_client)
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

    rm1 = LocalRedisManager(redis_client)
    rm2 = LocalRedisManager(redis_client)
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

    rm = LocalRedisManager(redis_client)
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


@pytest.mark.asyncio
async def test_heartbeat_interval_is_bounded_by_lease_ttl_and_watchdog():
    """Le battement est borné par le TTL du bail et les seuils watchdog, pas seulement par reclaim."""

    async def _noop(message: ProgressTaskMessage, retry_count: int, is_last: bool) -> None:
        return None

    # Configuration worker de production : le TTL du bail de 60 s est la borne
    # déterminante (et non la cadence de reclaim de ~100 s).
    worker = ThreadConsumer[ProgressTaskMessage](
        consumer_name="w",
        consumer_group="g",
        stream_name="s",
        batch_size=1,
        block_time=10,
        message_class=ProgressTaskMessage,
        process_message_callable=_noop,
        reclaim_idle_ms=300000,  # valeur par défaut
        step_progress_timeout_s=90.0,
        max_processing_time_s=120.0,
        use_execution_lease=True,
        lease_ttl_ms=60000,  # valeur par défaut
        current_redis_manager=None,
    )
    assert worker._heartbeat_interval_s <= 60.0 / 2
    assert worker._heartbeat_interval_s <= 90.0 / 2

    # Configuration API (pas de bail) : le plafond de 15 s de traitement est la
    # borne déterminante.
    api = ThreadConsumer[ProgressTaskMessage](
        consumer_name="w",
        consumer_group="g",
        stream_name="s",
        batch_size=1,
        block_time=10,
        message_class=ProgressTaskMessage,
        process_message_callable=_noop,
        reclaim_idle_ms=300000,
        step_progress_timeout_s=None,
        max_processing_time_s=15.0,
        use_execution_lease=False,
        lease_ttl_ms=60000,
        current_redis_manager=None,
    )
    assert api._heartbeat_interval_s <= 15.0 / 2


@pytest.mark.asyncio
async def test_stuck_thread_keeps_occupying_worker_slot(redis_client: Redis, stream: str):
    """Un handler bloqué conserve son slot de travail après un timeout watchdog."""
    group = f"group-{uuid4()}"
    exec1 = f"exec-{uuid4()}"
    exec2 = f"exec-{uuid4()}"

    block_event = threading.Event()
    seen_exec_ids: list[str] = []

    async def stuck_handler(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        seen_exec_ids.append(message.workflow_execution_id)
        if message.workflow_execution_id == exec1:
            await asyncio.to_thread(block_event.wait)

    msg1 = await redis_client.xadd(
        stream,
        {"data": json.dumps({"workflow_execution_id": exec1}), "retries": "0"},
    )

    rm = LocalRedisManager(redis_client)
    consumer = ThreadConsumer[ProgressTaskMessage](
        consumer_name=f"worker-{uuid4()}",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        drain_timeout_s=0.2,
        message_class=ProgressTaskMessage,
        process_message_callable=stuck_handler,
        reclaim_idle_ms=5000,
        step_progress_timeout_s=0.2,
        max_processing_time_s=5.0,
        max_retry_number=3,
        use_execution_lease=False,
        close_redis_on_stop=True,
        current_redis_manager=rm,
    )
    consumer._heartbeat_interval_s = 0.05

    await consumer.start()
    try:
        await wait_until(lambda: seen_exec_ids == [exec1], timeout=3.0)

        async def requeued_present() -> bool:
            entries = await redis_client.xrange(stream)
            return any(
                fields.get("retries") == "1" and fields.get("original_id") == msg1
                for _, fields in entries
            )

        await wait_until(requeued_present, timeout=3.0)

        # Le watchdog a avorté msg1, mais son thread reste bloqué : le worker
        # unique est donc toujours occupé. Publier msg2 ne doit pas l'admettre.
        msg2 = await redis_client.xadd(
            stream, {"data": json.dumps({"workflow_execution_id": exec2})}
        )
        await asyncio.sleep(0.4)

        assert seen_exec_ids == [exec1], (
            "msg2 must not be admitted while msg1's thread is still stuck"
        )
        assert msg2 not in consumer._in_flight_ids
        assert len(consumer._processing_futures) == 1
        assert all(not f.done() for f in consumer._processing_futures)

        # Une fois le thread débloqué, la capacité revient et msg2 est traité.
        block_event.set()
        await wait_until(lambda: exec2 in seen_exec_ids, timeout=3.0)
    finally:
        block_event.set()
        await consumer.stop()


@pytest.mark.asyncio
async def test_expired_lease_fences_handler_while_redis_unavailable(
    redis_client: Redis, stream: str
):
    """Un bail d'exécution expiré fence le handler même si Redis est injoignable.

    Le renouvellement n'avançant plus, l'expiration doit se calculer localement
    (dernier renouvellement confirmé + TTL) et non dépendre d'un aller-retour Redis.
    """
    group = f"group-{uuid4()}"
    exec_id = f"exec-{uuid4()}"
    await redis_client.xadd(
        stream, {"data": json.dumps({"workflow_execution_id": exec_id})}
    )

    started = threading.Event()
    release = threading.Event()
    aborted_seen = threading.Event()

    async def blocking_handler(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        started.set()
        tracker = get_current_progress_tracker()
        while not release.is_set():
            if tracker is not None and tracker.is_aborted:
                aborted_seen.set()
                return
            await asyncio.sleep(0.02)

    rm = LocalRedisManager(redis_client)
    consumer = ThreadConsumer[ProgressTaskMessage](
        consumer_name=f"worker-{uuid4()}",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        drain_timeout_s=0.2,
        message_class=ProgressTaskMessage,
        process_message_callable=blocking_handler,
        reclaim_idle_ms=60000,
        step_progress_timeout_s=30.0,
        max_processing_time_s=60.0,
        use_execution_lease=True,
        lease_ttl_ms=300,
        close_redis_on_stop=True,
        current_redis_manager=rm,
    )
    consumer._heartbeat_interval_s = 0.05

    await consumer.start()
    try:
        await wait_until(started.is_set, timeout=3.0)

        # Simule une coupure Redis : plus aucune connexion, donc plus de renouvellement.
        async def _no_connection() -> None:
            return None

        consumer._ensure_connection = _no_connection  # type: ignore[method-assign]

        await wait_until(aborted_seen.is_set, timeout=3.0)
        assert aborted_seen.is_set(), (
            "handler must be fenced once its last confirmed lease expires"
        )
    finally:
        release.set()
        await consumer.stop()


@pytest.mark.asyncio
async def test_shutdown_fences_unfinished_handler_before_releasing_lease(
    redis_client: Redis, stream: str
):
    """A l'arret, un handler threade non termine est fence avant la liberation de son bail.

    Liberer le bail en premier laisserait une livraison concurrente demarrer alors
    que le thread d'origine tourne encore et passe les gardes ``is_aborted``.
    """
    group = f"group-{uuid4()}"
    exec_id = f"exec-{uuid4()}"
    await redis_client.xadd(
        stream, {"data": json.dumps({"workflow_execution_id": exec_id})}
    )

    started = threading.Event()
    release = threading.Event()

    async def blocking_handler(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        started.set()
        await asyncio.to_thread(release.wait)

    rm = LocalRedisManager(redis_client)
    consumer = ThreadConsumer[ProgressTaskMessage](
        consumer_name=f"worker-{uuid4()}",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        drain_timeout_s=0.2,
        message_class=ProgressTaskMessage,
        process_message_callable=blocking_handler,
        reclaim_idle_ms=60000,
        step_progress_timeout_s=30.0,
        max_processing_time_s=60.0,
        use_execution_lease=True,
        lease_ttl_ms=60000,
        close_redis_on_stop=True,
        current_redis_manager=rm,
    )
    consumer._heartbeat_interval_s = 0.05

    # Espionne la libération du bail pour figer l'état du tracker à cet instant
    # précis : c'est l'ordre « fencer puis libérer » qui est vérifié ici.
    observed: dict[str, Any] = {}
    original_release = consumer.delivery.release_lease

    async def spy_release(
        redis_conn: Redis, execution_id: str, lease_token: str
    ) -> bool:
        if "aborted_at_release" not in observed:
            trackers_here = [
                c.tracker
                for c in consumer._in_flight_contexts.values()
                if c.execution_id == execution_id
            ]
            observed["aborted_at_release"] = bool(
                trackers_here and all(t.is_aborted for t in trackers_here)
            )
        observed["release_called"] = True
        return await original_release(redis_conn, execution_id, lease_token)

    consumer.delivery.release_lease = spy_release  # type: ignore[method-assign]

    lease_key = f"lock:workflow_execution:{exec_id}"
    await consumer.start()
    stop_task: Any = None
    try:
        await wait_until(started.is_set, timeout=3.0)
        assert await redis_client.get(lease_key) is not None

        stop_task = asyncio.create_task(consumer.stop())
        await wait_until(
            lambda: observed.get("aborted_at_release") is not None, timeout=6.0
        )
        assert observed.get("aborted_at_release") is True, (
            "handler must be fenced before its execution lease is released"
        )
        release.set()
        await asyncio.wait_for(stop_task, timeout=10.0)
        stop_task = None
    finally:
        release.set()
        if stop_task is not None:
            await asyncio.wait_for(stop_task, timeout=10.0)


@pytest.mark.asyncio
async def test_terminal_failure_callback_fires_when_watchdog_retries_exhausted(
    redis_client: Redis, stream: str
):
    """Le callback d'échec terminal est appelé après rétention DLQ et ACK.

    Une tentative fencée ne rapporte jamais son propre échec : sans ce callback
    l'exécution resterait bloquée à ``STARTED``, sans nouvelle tentative.
    """
    group = f"group-{uuid4()}"
    exec_id = f"exec-{uuid4()}"
    msg_id = await redis_client.xadd(
        stream,
        {"data": json.dumps({"workflow_execution_id": exec_id}), "retries": "2"},
    )

    started = threading.Event()
    calls: list[tuple[str, str]] = []

    async def on_terminal_failure(
        failed_msg_id: str, fields: dict[str, Any], reason: str
    ) -> None:
        calls.append((failed_msg_id, reason))

    async def endlessly_progressing_handler(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        started.set()
        while True:
            await asyncio.sleep(0.05)
            record_step_progress("minor_step")
            tracker = get_current_progress_tracker()
            if tracker and tracker.is_aborted:
                break

    rm = LocalRedisManager(redis_client)
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
        on_terminal_failure=on_terminal_failure,
    )
    consumer._heartbeat_interval_s = 0.05

    await consumer.start()
    try:
        await wait_until(started.is_set, timeout=3.0)
        await wait_until(lambda: len(calls) == 1, timeout=3.0)
        assert calls == [(msg_id, "workflow_timeout")]

        # Le message a bien été retenu en DLQ avant la notification.
        dlq_entries = await redis_client.xrange(f"{stream}:dlq")
        assert any(fields.get("original_id") == msg_id for _, fields in dlq_entries)
    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_blocking_terminal_failure_callback_does_not_stall_heartbeat(
    redis_client: Redis, stream: str
):
    """Un callback d'échec terminal bloquant ne doit pas geler la boucle de battement.

    S'il y était attendu, les autres messages en timeout ne seraient plus traités :
    plus de rejeu, plus de renouvellement de bail, plus de fencing local.
    """
    group = f"group-{uuid4()}"
    terminal_exec = f"exec-{uuid4()}"
    retry_exec = f"exec-{uuid4()}"

    await redis_client.xadd(
        stream,
        {"data": json.dumps({"workflow_execution_id": terminal_exec}), "retries": "2"},
    )
    retry_msg_id = await redis_client.xadd(
        stream,
        {"data": json.dumps({"workflow_execution_id": retry_exec}), "retries": "0"},
    )

    callback_started = threading.Event()
    callback_release = threading.Event()

    async def blocking_terminal_failure(
        failed_msg_id: str, fields: dict[str, Any], reason: str
    ) -> None:
        callback_started.set()
        await asyncio.to_thread(callback_release.wait)

    async def endlessly_progressing_handler(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        while True:
            await asyncio.sleep(0.05)
            record_step_progress("minor_step")
            tracker = get_current_progress_tracker()
            if tracker and tracker.is_aborted:
                break

    rm = LocalRedisManager(redis_client)
    consumer = ThreadConsumer[ProgressTaskMessage](
        consumer_name=f"worker-{uuid4()}",
        consumer_group=group,
        stream_name=stream,
        batch_size=2,
        block_time=10,
        drain_timeout_s=0.2,
        message_class=ProgressTaskMessage,
        process_message_callable=endlessly_progressing_handler,
        worker_number=2,
        reclaim_idle_ms=60000,
        step_progress_timeout_s=1.0,
        max_processing_time_s=0.3,
        max_retry_number=3,
        use_execution_lease=True,
        close_redis_on_stop=True,
        current_redis_manager=rm,
        on_terminal_failure=blocking_terminal_failure,
    )
    consumer._heartbeat_interval_s = 0.05

    await consumer.start()
    try:
        await wait_until(callback_started.is_set, timeout=5.0)

        async def retry_copy_present() -> bool:
            entries = await redis_client.xrange(stream)
            return any(
                fields.get("retries") == "1"
                and fields.get("original_id") == retry_msg_id
                for _, fields in entries
            )

        assert not callback_release.is_set()
        await wait_until(retry_copy_present, timeout=3.0)
    finally:
        callback_release.set()
        await consumer.stop()


@pytest.mark.asyncio
async def test_worker_shutdown_path_drains_terminal_failure_tasks(
    redis_client: Redis, stream: str
):
    """Le chemin d'arrêt du worker (``_de_init_consumer``) doit drainer les notifications.

    ``start_consumer()`` termine par ``_de_init_consumer()`` et non par
    ``_stop_tasks_only()`` : sans drain partagé, une notification en cours serait
    annulée à la sortie du processus alors que le message est déjà acquitté,
    perdant définitivement l'échec terminal de l'exécution.
    """
    async def endless_handler(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        while True:
            await asyncio.sleep(0.05)

    rm = LocalRedisManager(redis_client)
    consumer = ThreadConsumer[ProgressTaskMessage](
        consumer_name=f"worker-{uuid4()}",
        consumer_group=f"group-{uuid4()}",
        stream_name=stream,
        batch_size=1,
        block_time=10,
        drain_timeout_s=0.2,
        message_class=ProgressTaskMessage,
        process_message_callable=endless_handler,
        reclaim_idle_ms=60000,
        step_progress_timeout_s=30.0,
        max_processing_time_s=60.0,
        use_execution_lease=True,
        close_redis_on_stop=True,
        current_redis_manager=rm,
    )

    released = threading.Event()

    async def blocking_callback(*_args: Any) -> None:
        await asyncio.to_thread(released.wait)

    consumer.on_terminal_failure = blocking_callback
    task = asyncio.create_task(
        consumer._run_terminal_failure_callback("1-0", {}, "workflow_timeout")
    )
    consumer._terminal_failure_tasks.add(task)
    task.add_done_callback(consumer._terminal_failure_tasks.discard)

    shutdown = asyncio.create_task(consumer._de_init_consumer())
    try:
        await asyncio.sleep(0.2)
        assert not shutdown.done(), (
            "shutdown must wait for the outstanding notification"
        )

        released.set()
        await asyncio.wait_for(shutdown, timeout=5.0)
        assert task.done()
        assert not task.cancelled()
    finally:
        # Ne jamais laisser un callback bloqué retenir la boucle (ni le thread).
        released.set()
        await asyncio.wait_for(shutdown, timeout=5.0)


@pytest.mark.asyncio
async def test_shutdown_aborted_delivery_is_not_acknowledged(
    redis_client: Redis, stream: str
):
    """Une livraison abandonnée à l'arrêt doit rester en attente, pas être acquittée.

    Le handler fencé revient « en succès » (il saute la persistance) : l'acquitter
    laisserait l'exécution inachevée, sans message en attente ni reprise planifiée.
    """
    group = f"group-{uuid4()}"
    exec_id = f"exec-{uuid4()}"
    await redis_client.xadd(
        stream, {"data": json.dumps({"workflow_execution_id": exec_id})}
    )

    started = threading.Event()
    release = threading.Event()

    async def blocking_handler(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        started.set()
        await asyncio.to_thread(release.wait)

    rm = LocalRedisManager(redis_client)
    consumer = ThreadConsumer[ProgressTaskMessage](
        consumer_name=f"worker-{uuid4()}",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        drain_timeout_s=0.2,
        message_class=ProgressTaskMessage,
        process_message_callable=blocking_handler,
        reclaim_idle_ms=60000,
        step_progress_timeout_s=30.0,
        max_processing_time_s=60.0,
        use_execution_lease=True,
        lease_ttl_ms=60000,
        close_redis_on_stop=True,
        current_redis_manager=rm,
    )
    consumer._heartbeat_interval_s = 0.05

    await consumer.start()
    stop_task: Any = None
    try:
        await wait_until(started.is_set, timeout=3.0)
        stop_task = asyncio.create_task(consumer.stop())

        # Laisser le drain expirer pour que l'abandon (fencing) ait lieu, puis
        # laisser le handler threadé se terminer « normalement ».
        await asyncio.sleep(0.6)
        release.set()
        await asyncio.wait_for(stop_task, timeout=10.0)
        stop_task = None

        info = await redis_client.xpending(stream, group)
        pending = info["pending"] if isinstance(info, dict) else info.pending
        assert pending == 1, (
            "an aborted-at-shutdown delivery must stay pending for recovery"
        )
    finally:
        release.set()
        if stop_task is not None:
            await asyncio.wait_for(stop_task, timeout=10.0)


@pytest.mark.asyncio
async def test_fenced_tracker_completion_is_never_acknowledged():
    """Un handler fencé qui se termine proprement ne doit pas être acquitté en succès.

    Couvre la fenêtre où une future se termine entre le fencing et sa reprise par
    le battement : le listener finalise alors la future et acquitterait à tort le
    message, laissant l'exécution inachevée sans livraison en attente ni reprise.
    """
    async def noop_handler(
        message: ProgressTaskMessage, retry_count: int, is_last: bool
    ) -> None:
        return None

    consumer = ThreadConsumer[ProgressTaskMessage](
        consumer_name="worker-1",
        consumer_group="group-1",
        stream_name="stream-1",
        batch_size=1,
        block_time=10,
        message_class=ProgressTaskMessage,
        process_message_callable=noop_handler,
        use_execution_lease=True,
        lease_ttl_ms=60000,
    )

    tracker = ProgressTracker(msg_id="1-0", max_processing_time_s=60.0)
    tracker.abort("lease_lost")
    consumer._in_flight_contexts["1-0"] = InFlightContext(
        msg_id="1-0",
        fields={"data": "{}"},
        tracker=tracker,
        execution_id="exec-1",
        lease_token="worker-1:token",
    )
    consumer._in_flight_ids.add("1-0")

    future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    future.set_result(None)
    active_futures: dict[asyncio.Future[Any], tuple[str, dict[str, Any]]] = {
        future: ("1-0", {"data": "{}"})
    }

    acked: list[str] = []

    async def spy_ack(_redis: Any, msg_id: str) -> None:
        acked.append(msg_id)

    consumer.delivery.ack = spy_ack  # type: ignore[method-assign]

    await consumer._finalize_done_futures([future], active_futures, object())  # type: ignore[arg-type]

    assert acked == [], "a fenced attempt must never be acknowledged as success"
    assert "1-0" not in consumer._in_flight_ids
