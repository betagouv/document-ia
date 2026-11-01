import asyncio
import contextlib
import json
import time
from collections.abc import Callable
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
        self.xadd_ids: list[str] = []  # generated id per xadd call, same order
        self.xrange_calls: list[tuple[str, str, str]] = []  # (stream, min, max)
        self.groups_created: set[tuple[str, str]] = set()
        self._id_state: dict[str, tuple[int, int]] = {}  # per-stream (ms, seq)
        self._clock: Callable[[], int] = lambda: time.time_ns() // 1_000_000
        self._xautoclaim_queue: list[
            tuple[str, list[tuple[str, dict[str, Any]]], list[str]]
        ] = []
        self.closed = False

    def queue_xread_batch(self, entries: list[tuple[str, dict[str, Any]]]):
        self._xread_batches.append(entries)

    def queue_xautoclaim(
        self, next_start: str, claimed: list[tuple[str, dict[str, Any]]]
    ):
        self._xautoclaim_queue.append((next_start, claimed, []))

    async def ping(self):
        return True

    async def close(self):
        self.closed = True

    async def xgroup_create(self, name: str, groupname: str, id: str, mkstream: bool):
        self.groups_created.add((name, groupname))
        return True

    async def xreadgroup(
        self, group: str, consumer: str, streams: dict[str, str], count: int, block: int
    ):
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
        # séquences indépendantes par flux, comme en Redis réel
        now_ms = self._clock()
        last_ms, last_seq = self._id_state.get(stream, (0, 0))
        if now_ms > last_ms:
            msg_id = f"{now_ms}-0"
        else:
            msg_id = f"{last_ms}-{last_seq + 1}"
        self._id_state[stream] = self._id_key(msg_id)
        self.xadd_calls.append((stream, dict(fields)))
        self.xadd_ids.append(msg_id)
        return msg_id

    @staticmethod
    def _id_key(stream_id: str) -> tuple[int, int]:
        ms, seq = stream_id.split("-")
        return (int(ms), int(seq))

    async def xrange(
        self, stream: str, min: str = "-", max: str = "+", count: int | None = None
    ):
        self.xrange_calls.append((stream, min, max))
        entries = [
            (msg_id, dict(fields))
            for (recorded_stream, fields), msg_id in zip(self.xadd_calls, self.xadd_ids)
            if recorded_stream == stream
        ]
        lower = None if min == "-" else self._id_key(min)
        upper = None if max == "+" else self._id_key(max)
        result = []
        for msg_id, fields in entries:
            key = self._id_key(msg_id)
            if lower is not None and key < lower:
                continue
            if upper is not None and key > upper:
                continue
            result.append((msg_id, fields))
        if count is not None:
            result = result[:count]
        return result

    async def xautoclaim(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        start: str,
        count: int,
    ):
        if self._xautoclaim_queue:
            return self._xautoclaim_queue.pop(0)
        await asyncio.sleep(0.01)
        return (start, [], [])

    async def eval(self, script: str, numkeys: int, *args: Any):
        # Émule les scripts Lua de remise en file et de conservation DLQ :
        # recherche d'une copie portant « original_id » puis XADD si absente,
        # de façon atomique. Le flux cible est args[0].
        stream = args[0]
        orig = args[1]
        # Recherche d'une copie existante avec original_id == orig.
        for (recorded_stream, fields), msg_id in zip(self.xadd_calls, self.xadd_ids):
            if recorded_stream == stream and str(fields.get("original_id", "")) == str(
                orig
            ):
                return [0, msg_id]
        if stream == self.stream_name:
            # Remise en file : data, retries, original_id.
            fields = {"data": args[3], "retries": args[2], "original_id": orig}
        else:
            # Conservation DLQ : paires clé/valeur après original_id.
            fields = {}
            rest = args[2:]
            for i in range(0, len(rest), 2):
                fields[rest[i]] = rest[i + 1]
            fields["original_id"] = orig
        new_id = await self.xadd(stream, fields)
        return [1, new_id]


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
    assert any(
        call[0] == stream and call[1].get("retries") == "1"
        for call in mock_redis.xadd_calls
    )


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
async def test_reclaimer_reclaim_consumes_single_attempt(monkeypatch):
    """Une récupération consomme exactement une tentative : le message remis
    en file porte une tentative de plus, pas deux (issue #111)."""
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
        max_retry_number=3,
    )

    msg1 = ("1700000000000-0", {"data": json.dumps({"a": 1}), "retries": "0"})
    msg2 = ("1700000000001-0", {"data": json.dumps({"a": 2}), "retries": "1"})

    mock_redis.queue_xautoclaim("0-1", [msg1, msg2])

    # start reclaimer and stop after one pass
    task = asyncio.create_task(c._reclaim_pending_messages())
    await asyncio.sleep(0.1)
    c.stop_flag.set()
    await asyncio.wait_for(task, timeout=2)

    requeues = [call for call in mock_redis.xadd_calls if call[0] == stream]
    assert requeues == [
        (
            stream,
            {
                "data": json.dumps({"a": 1}),
                "retries": "1",
                "original_id": "1700000000000-0",
            },
        ),
        (
            stream,
            {
                "data": json.dumps({"a": 2}),
                "retries": "2",
                "original_id": "1700000000001-0",
            },
        ),
    ]
    assert (stream, "1700000000000-0") in mock_redis.acks
    assert (stream, "1700000000001-0") in mock_redis.acks
    # aucune conservation DLQ : les deux messages avaient encore des tentatives
    assert all(call[0] != f"{stream}:dlq" for call in mock_redis.xadd_calls)


@pytest.mark.asyncio
async def test_reclaimer_exhausted_uses_same_threshold_as_worker(monkeypatch):
    """Le seuil d'épuisement est identique au chemin d'erreur du worker :
    à max_retry_number=3, une entrée récupérée avec retries=2 (dernière
    tentative consommable) part en DLQ et est acquittée après conservation
    confirmée (issue #111)."""
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
        max_retry_number=3,
    )

    msg = ("1700000000000-0", {"data": json.dumps({"a": 1}), "retries": "2"})
    mock_redis.queue_xautoclaim("0-1", [msg])

    task = asyncio.create_task(c._reclaim_pending_messages())
    await asyncio.sleep(0.1)
    c.stop_flag.set()
    await asyncio.wait_for(task, timeout=2)

    requeues = [call for call in mock_redis.xadd_calls if call[0] == stream]
    dlqs = [call for call in mock_redis.xadd_calls if call[0] == f"{stream}:dlq"]
    assert requeues == []
    assert len(dlqs) == 1
    assert dlqs[0][1].get("reason") == "max_retries_exceeded"
    assert dlqs[0][1].get("original_id") == "1700000000000-0"
    assert (stream, "1700000000000-0") in mock_redis.acks


@pytest.mark.asyncio
async def test_dlq_retention_is_idempotent_per_message(monkeypatch):
    """Une conservation DLQ déjà confirmée n'est pas réécrite : _send_to_dlq
    détecte l'entrée existante via original_id et confirme la conservation
    sans nouvelle écriture (issue #111)."""
    stream = "test-stream"

    mock_redis = MockRedis(stream)

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module

    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    c = Consumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
        worker_number=1,
        max_retry_number=3,
    )

    fields = {"data": json.dumps({"a": 1}), "retries": "2"}
    msg_id = "1700000000000-0"

    first = await c._send_to_dlq(
        mock_redis, msg_id, fields, "max_retries_exceeded", "err"
    )
    second = await c._send_to_dlq(
        mock_redis, msg_id, fields, "max_retries_exceeded", "err"
    )

    assert first is True
    assert second is True
    dlqs = [call for call in mock_redis.xadd_calls if call[0] == f"{stream}:dlq"]
    assert len(dlqs) == 1


@pytest.mark.asyncio
async def test_dlq_retention_dedup_per_original_id():
    """Une deuxième conservation pour le même « original_id » ne crée pas de
    doublon ; une conservation pour un autre message est indépendante."""
    stream = "test-stream"
    mock_redis = MockRedis(stream)

    c = Consumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
        worker_number=1,
        max_retry_number=3,
    )

    retained_id = "1700000000000-0"
    fields = {"data": json.dumps({"a": 1}), "retries": "2"}
    assert await c._send_to_dlq(mock_redis, retained_id, fields, "max_retries_exceeded")
    # deuxième conservation du même message : aucune nouvelle ligne
    assert await c._send_to_dlq(mock_redis, retained_id, fields, "max_retries_exceeded")
    # un autre message est conservé indépendamment
    assert await c._send_to_dlq(
        mock_redis, "1700000000001-0", fields, "max_retries_exceeded"
    )

    dlqs = [call for call in mock_redis.xadd_calls if call[0] == f"{stream}:dlq"]
    originals = sorted(call[1]["original_id"] for call in dlqs)
    assert originals == ["1700000000000-0", "1700000000001-0"]


@pytest.mark.asyncio
async def test_dlq_retention_detects_same_millisecond_copy():
    """Séquences indépendantes par flux : une copie DLQ créée dans la même
    milliseconde que le message d'origine peut précéder son identifiant
    (source T-5, DLQ T-0) et doit rester détectée."""
    stream = "test-stream"
    mock_redis = MockRedis(stream)
    mock_redis._clock = lambda: 12345  # milliseconde figée

    c = Consumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
        worker_number=1,
        max_retry_number=3,
    )

    # six entrées du flux source dans la même milliseconde : la dernière
    # porte le numéro de séquence 5
    source_id = ""
    for _ in range(6):
        source_id = await mock_redis.xadd(stream, {"data": "x"})
    assert source_id == "12345-5"

    fields = {"data": json.dumps({"a": 1}), "retries": "0"}
    assert await c._send_to_dlq(mock_redis, source_id, fields, "decode_error")

    # la copie DLQ de la même milliseconde porte la séquence 0 du flux DLQ :
    # son identifiant précède celui du message d'origine
    assert mock_redis.xadd_ids[-1] == "12345-0"

    # une nouvelle conservation retrouve l'entrée : pas de doublon
    assert await c._send_to_dlq(mock_redis, source_id, fields, "decode_error")
    dlqs = [call for call in mock_redis.xadd_calls if call[0] == f"{stream}:dlq"]
    assert len(dlqs) == 1


@pytest.mark.asyncio
async def test_reclaimer_after_dlq_retention_does_not_duplicate(monkeypatch):
    """Conservation DLQ confirmée puis ACK en échec : l'entrée d'origine
    reste en attente et subit une nouvelle récupération, qui ne doit pas
    conserver une deuxième copie (issue #111)."""
    stream = "test-stream"
    group = "g1"
    msg_id = "1700000000000-0"
    fields = {"data": json.dumps({"a": 1}), "retries": "2"}

    mock_redis = MockRedis(stream)

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module

    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    c = Consumer[SampleMessage](
        consumer_name="c1",
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
        worker_number=1,
        max_retry_number=3,
    )

    # deux cycles de récupération sur la même entrée épuisée
    mock_redis.queue_xautoclaim("0-1", [(msg_id, dict(fields))])
    mock_redis.queue_xautoclaim("0-1", [(msg_id, dict(fields))])

    # l'ACK échoue : l'entrée reste en attente après la conservation DLQ
    async def failing_xack(stream_name: str, group_name: str, mid: str):
        raise RuntimeError("ack failed")

    mock_redis.xack = failing_xack  # type: ignore

    task = asyncio.create_task(c._reclaim_pending_messages())
    try:
        # le second cycle doit retrouver l'entrée déjà conservée (dédup
        # atomique dans le script Lua) : aucune seconde ligne DLQ.
        for _ in range(100):
            if mock_redis.xadd_calls:
                break
            await asyncio.sleep(0.05)
        # laisser le second cycle se dérouler
        await asyncio.sleep(0.3)
    finally:
        c.stop_flag.set()
        await asyncio.wait_for(task, timeout=5)

    dlqs = [call for call in mock_redis.xadd_calls if call[0] == f"{stream}:dlq"]
    assert len(dlqs) == 1


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
        call[0] == f"{stream}:dlq"
        and call[1].get("reason") == "error_requeueing_message"
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
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
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


@pytest.mark.asyncio
async def test_shutdown_leaves_blocked_message_unacked(monkeypatch):
    import threading

    monkeypatch.setattr(
        "document_ia_infra.redis.consumer.IN_FLIGHT_SHUTDOWN_TIMEOUT_S", 0.05
    )
    started = threading.Event()
    release = threading.Event()
    msg_id = "1700000000000-0"
    mock_redis = MockRedis("test-stream")
    mock_redis.queue_xread_batch(
        [(msg_id, {"data": json.dumps({"blocked": True}), "retries": "0"})]
    )

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module

    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    async def process_blocked(*_args):
        started.set()
        release.wait()

    consumer = Consumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name="test-stream",
        batch_size=1,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=process_blocked,
        worker_number=1,
    )
    listener = asyncio.create_task(consumer._start_listening_messages())
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set(), "Processing did not start within the expected time"

        consumer.stop_flag.set()
        await asyncio.wait_for(listener, timeout=1)

        assert mock_redis.acks == []
        assert consumer.has_running_handlers
    finally:
        release.set()
        if not listener.done():
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
        consumer.executor.shutdown(wait=True)
        await asyncio.sleep(0.01)
    assert not consumer.has_running_handlers


@pytest.mark.asyncio
async def test_executor_shutdown_does_not_wait_for_running_threads(monkeypatch):
    stream = "test-stream"
    consumer = Consumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name=stream,
        batch_size=1,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=lambda *_args: asyncio.sleep(0),
    )
    shutdown_calls = []

    class Executor:
        def shutdown(self, *, wait, cancel_futures):
            shutdown_calls.append((wait, cancel_futures))

    async def close_redis():
        return None

    consumer.executor = Executor()
    monkeypatch.setattr(
        "document_ia_infra.redis.consumer.redis_manager_main_thread.close",
        close_redis,
    )

    await consumer._de_init_consumer()

    assert shutdown_calls == [(False, True)]


@pytest.mark.asyncio
async def test_requeue_survives_cancellation_after_atomic_redis_write():
    class CancelAfterAtomicWriteRedis(MockRedis):
        def __init__(self, stream_name: str):
            super().__init__(stream_name)
            self.cancel_after_write = True

        async def eval(self, *args):
            result = await super().eval(*args)
            if self.cancel_after_write:
                self.cancel_after_write = False
                raise asyncio.CancelledError
            return result

    stream = "test-stream"
    group = "g1"
    msg_id = "1700000000000-0"
    mock_redis = CancelAfterAtomicWriteRedis(stream)
    consumer = Consumer[SampleMessage](
        consumer_name="c1",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=lambda *_args: asyncio.sleep(0),
    )
    consumer.redis = mock_redis
    fields = {"data": json.dumps({"payload": "recover"}), "retries": "1"}

    with pytest.raises(asyncio.CancelledError):
        await consumer._reclaim_entry(msg_id, fields.copy())
    assert mock_redis.acks == []

    await consumer._reclaim_entry(msg_id, fields.copy())

    copies = [
        fields
        for recorded_stream, fields in mock_redis.xadd_calls
        if recorded_stream == stream and fields.get("original_id") == msg_id
    ]
    assert len(copies) == 1
    assert mock_redis.acks == [(stream, msg_id)]
    consumer.executor.shutdown(wait=True)
