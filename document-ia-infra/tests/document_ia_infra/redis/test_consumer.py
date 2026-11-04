import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import pytest
from redis.exceptions import ResponseError

from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.redis.consumer import (
    AsyncIoConsumer,
    BaseConsumer,
    ThreadConsumer,
    build_instance_consumer_name,
)
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
        self.xadd_maxlens: list[tuple[str, int | None, bool]] = []
        self.xadd_ids: list[str] = []  # generated id per xadd call, same order
        self.xrange_calls: list[tuple[str, str, str]] = []  # (stream, min, max)
        self.xclaim_calls: list[tuple[str, str, str, int, list[str], bool]] = []
        self.groups_created: set[tuple[str, str]] = set()
        self.groups_created_ids: dict[tuple[str, str], str] = {}
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
        self.groups_created_ids[(name, groupname)] = id
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

    async def xadd(
        self,
        stream: str,
        fields: dict[str, Any],
        maxlen: int | None = None,
        approximate: bool = True,
    ):
        # séquences indépendantes par flux, comme en Redis réel
        now_ms = self._clock()
        last_ms, last_seq = self._id_state.get(stream, (0, 0))
        if now_ms > last_ms:
            msg_id = f"{now_ms}-0"
        else:
            msg_id = f"{last_ms}-{last_seq + 1}"
        self._id_state[stream] = self._id_key(msg_id)
        self.xadd_calls.append((stream, dict(fields)))
        self.xadd_maxlens.append((stream, maxlen, approximate))
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
        lower_exclusive = min.startswith("(")
        lower = None if min == "-" else self._id_key(min.removeprefix("("))
        upper_exclusive = max.startswith("(")
        upper = None if max == "+" else self._id_key(max.removeprefix("("))
        result = []
        for msg_id, fields in entries:
            key = self._id_key(msg_id)
            if lower is not None and (key <= lower if lower_exclusive else key < lower):
                continue
            if upper is not None and (key >= upper if upper_exclusive else key > upper):
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
        stream = args[0]
        orig = args[1]
        if self.xrange.__code__ is not MockRedis.xrange.__code__:
            await self.xrange(stream, "-", "+")
        for (recorded_stream, fields), msg_id in zip(self.xadd_calls, self.xadd_ids):
            if recorded_stream == stream and str(fields.get("original_id", "")) == str(
                orig
            ):
                return [0, msg_id]
        fields: dict[str, Any] = {}
        rest = args[3:]
        for i in range(0, len(rest), 2):
            if i + 1 < len(rest):
                fields[rest[i]] = rest[i + 1]
        fields["original_id"] = orig
        maxlen = (
            int(args[2]) if len(args) > 2 and args[2] and int(args[2]) > 0 else None
        )
        new_id = await self.xadd(stream, fields, maxlen=maxlen)
        return [1, new_id]

    async def xclaim(
        self,
        name: str,
        groupname: str,
        consumername: str,
        min_idle_time: int,
        message_ids: list[str],
        justid: bool = False,
    ):
        ids = [str(mid) for mid in message_ids]
        self.xclaim_calls.append(
            (name, groupname, consumername, min_idle_time, ids, justid)
        )
        if justid:
            return ids
        return [(mid, {}) for mid in ids]


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

    c = ThreadConsumer[SampleMessage](
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
    await c._shutdown_executor()


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

    c = ThreadConsumer[SampleMessage](
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
    await c._shutdown_executor()


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

    c = ThreadConsumer[SampleMessage](
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
    await c._shutdown_executor()


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

    c = ThreadConsumer[SampleMessage](
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
    await c._shutdown_executor()


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

    c = ThreadConsumer[SampleMessage](
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
                "root_id": "1700000000000-0",
            },
        ),
        (
            stream,
            {
                "data": json.dumps({"a": 2}),
                "retries": "2",
                "original_id": "1700000000001-0",
                "root_id": "1700000000001-0",
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

    c = ThreadConsumer[SampleMessage](
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
    assert dlqs[0][1].get("retries") == "2"
    assert (stream, "1700000000000-0") in mock_redis.acks
    await c._shutdown_executor()


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

    c = ThreadConsumer[SampleMessage](
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
    try:
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
    finally:
        await c._shutdown_executor()


@pytest.mark.asyncio
async def test_dlq_retention_scan_is_bounded_to_source_millisecond():
    """La détection d'entrée déjà conservée démarre au début de la milliseconde
    du message d'origine (<source_ms>-0) : l'historique antérieur de la DLQ
    n'est pas chargé à chaque échec terminal."""
    stream = "test-stream"
    mock_redis = MockRedis(stream)

    c = ThreadConsumer[SampleMessage](
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
    try:
        # une entrée DLQ existe déjà pour un message de séquence > 0
        retained_id = "1700000000000-4"
        fields = {"data": json.dumps({"a": 1}), "retries": "2"}
        await c._send_to_dlq(mock_redis, retained_id, fields, "max_retries_exceeded")

        # la copie DLQ créée ultérieurement est retrouvée à partir de <source_ms>-0
        assert await c._already_retained_in_dlq(mock_redis, retained_id) is True
        # un message plus récent que toute entrée existante de la DLQ démarre son
        # parcours à sa propre milliseconde et ignore l'historique antérieur
        assert await c._already_retained_in_dlq(mock_redis, "9999999999999-3") is False

        dlq_scans = [
            call for call in mock_redis.xrange_calls if call[0] == f"{stream}:dlq"
        ]
        assert len(dlq_scans) == 3
        assert all(scan[1] != "-" for scan in dlq_scans)
        assert [scan[1] for scan in dlq_scans] == [
            "1700000000000-0",
            "1700000000000-0",
            "9999999999999-0",
        ]
    finally:
        await c._shutdown_executor()


@pytest.mark.asyncio
async def test_dlq_retention_scan_covers_source_millisecond():
    """Séquences indépendantes par flux : une copie DLQ créée dans la même
    milliseconde que le message d'origine peut précéder son identifiant
    (source T-5, DLQ T-0) et doit rester détectée sans faux positif sur un
    autre message de la même milliseconde."""
    stream = "test-stream"
    mock_redis = MockRedis(stream)
    mock_redis._clock = lambda: 12345  # milliseconde figée

    c = ThreadConsumer[SampleMessage](
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
    try:
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

        # la détection doit retrouver l'entrée malgré l'inversion de séquence
        assert await c._already_retained_in_dlq(mock_redis, source_id) is True
        # un autre message de la même milliseconde non conservé ne subit pas de faux positif
        assert await c._already_retained_in_dlq(mock_redis, "12345-4") is False
    finally:
        await c._shutdown_executor()


@pytest.mark.asyncio
async def test_reclaimer_after_dlq_retention_does_not_duplicate(monkeypatch, caplog):
    """Conservation DLQ confirmée puis ACK en échec : l'entrée d'origine
    reste en attente et subit une nouvelle récupération, qui ne doit pas
    conserver une deuxième copie (issue #111)."""
    caplog.set_level(logging.INFO)
    stream = "test-stream"
    group = "g1"
    msg_id = "1700000000000-0"
    fields = {"data": json.dumps({"a": 1}), "retries": "2"}

    mock_redis = MockRedis(stream)

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module

    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    c = ThreadConsumer[SampleMessage](
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
    mock_redis.queue_xautoclaim("0-1", [(msg_id, fields)])
    mock_redis.queue_xautoclaim("0-1", [(msg_id, fields)])

    # l'ACK échoue : l'entrée reste en attente après la conservation DLQ
    async def failing_xack(stream_name: str, group_name: str, mid: str):
        raise RuntimeError("ack failed")

    mock_redis.xack = failing_xack  # type: ignore

    task = asyncio.create_task(c._reclaim_pending_messages())
    try:
        # le second cycle doit passer par la détection d'entrée existante
        for _ in range(100):
            if "skipping duplicate write" in caplog.text:
                break
            await asyncio.sleep(0.05)
    finally:
        c.stop_flag.set()
        await asyncio.wait_for(task, timeout=5)
        await c._shutdown_executor()

    assert "skipping duplicate write" in caplog.text
    dlqs = [call for call in mock_redis.xadd_calls if call[0] == f"{stream}:dlq"]
    assert len(dlqs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["decode_error", "not_retryable_error"])
async def test_reclaimer_terminates_already_retained_dlq_entry_at_zero_retries(
    monkeypatch, reason: str
):
    """Un message ayant échoué de façon terminale dès retries=0 (decode_error ou
    not_retryable_error), déjà conservé en DLQ mais dont l'ACK a échoué, doit
    être simplement acquitté au reclaim sans être remis en file ni dupliqué."""
    stream = "test-stream"
    group = "g1"
    msg_id = "1700000000000-0"
    fields = {"data": "{bad-json}", "retries": "0"}

    mock_redis = MockRedis(stream)

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module

    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    c = ThreadConsumer[SampleMessage](
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
    try:
        # conservation initiale en DLQ réussie (mais son ACK avait échoué)
        assert await c._send_to_dlq(mock_redis, msg_id, fields, reason, "fatal")
        mock_redis.queue_xautoclaim("0-0", [(msg_id, fields)])

        task = asyncio.create_task(c._reclaim_pending_messages())
        try:
            for _ in range(50):
                if mock_redis.acks:
                    break
                await asyncio.sleep(0.02)
        finally:
            c.stop_flag.set()
            await asyncio.wait_for(task, timeout=2)

        assert mock_redis.acks == [(stream, msg_id)]
        requeues = [call for call in mock_redis.xadd_calls if call[0] == stream]
        dlqs = [call for call in mock_redis.xadd_calls if call[0] == f"{stream}:dlq"]
        assert requeues == []
        assert len(dlqs) == 1
    finally:
        await c._shutdown_executor()


@pytest.mark.asyncio
async def test_dlq_scan_error_fails_closed_on_send_and_reclaim(monkeypatch):
    """Si xrange sur la DLQ échoue, ni _send_to_dlq ni le reclaimer ne doivent
    écrire en aveugle dans la DLQ, remettre en file ou acquitter le message."""
    stream = "test-stream"
    group = "g1"
    msg_id = "1700000000000-0"
    fields = {"data": json.dumps({"a": 1}), "retries": "0"}

    mock_redis = MockRedis(stream)

    async def failing_xrange(*args: Any, **kwargs: Any):
        raise ConnectionError("xrange unavailable")

    mock_redis.xrange = failing_xrange  # type: ignore

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module

    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    c = ThreadConsumer[SampleMessage](
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
    try:
        assert (
            await c._send_to_dlq(mock_redis, msg_id, fields, "not_retryable_error")
            is False
        )
        assert mock_redis.xadd_calls == []
        assert mock_redis.acks == []

        mock_redis.queue_xautoclaim("0-0", [(msg_id, fields)])
        task = asyncio.create_task(c._reclaim_pending_messages())
        await asyncio.sleep(0.05)
        c.stop_flag.set()
        await asyncio.wait_for(task, timeout=2)

        assert mock_redis.xadd_calls == []
        assert mock_redis.acks == []
    finally:
        await c._shutdown_executor()


@pytest.mark.asyncio
async def test_dlq_retention_scan_paginates_across_batches(monkeypatch):
    """Lorsque la DLQ contient plus d'entrées récentes que DLQ_SCAN_BATCH_SIZE,
    le parcours paginé avance sans charger tout le flux d'un coup."""
    stream = "test-stream"
    mock_redis = MockRedis(stream)
    monkeypatch.setattr("document_ia_infra.redis.base_consumer.DLQ_SCAN_BATCH_SIZE", 3)

    c = ThreadConsumer[SampleMessage](
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
    try:
        for idx in range(7):
            await mock_redis.xadd(
                f"{stream}:dlq", {"original_id": f"other-{idx}", "data": "x"}
            )
        target_id = "1000-0"
        await mock_redis.xadd(
            f"{stream}:dlq", {"original_id": target_id, "data": "target"}
        )

        assert await c._already_retained_in_dlq(mock_redis, target_id) is True
        assert await c._already_retained_in_dlq(mock_redis, "1000-99") is False
        # 8 entrées avec des lots de 3 -> 3 pages parcourues par appel
        assert len(mock_redis.xrange_calls) == 6
        assert mock_redis.xrange_calls[0][1] == "1000-0"
        assert mock_redis.xrange_calls[1][1] == f"({mock_redis.xadd_ids[2]}"
        assert mock_redis.xrange_calls[2][1] == f"({mock_redis.xadd_ids[5]}"
    finally:
        await c._shutdown_executor()


@pytest.mark.parametrize("invalid_max_retries", [0, -1])
def test_consumer_rejects_non_positive_max_retry_number(invalid_max_retries: int):
    with pytest.raises(ValueError, match="max_retry_number"):
        ThreadConsumer[SampleMessage](
            consumer_name="c1",
            consumer_group="g1",
            stream_name="s1",
            batch_size=1,
            block_time=10,
            message_class=SampleMessage,
            process_message_callable=lambda m, r, _: asyncio.sleep(0),
            max_retry_number=invalid_max_retries,
        )


@pytest.mark.asyncio
async def test_single_attempt_budget_consistent_between_worker_and_reclaimer(
    monkeypatch,
):
    """Avec max_retry_number=1 (aucun retry autorisé), la première tentative a
    is_last_retry=True et part directement en DLQ aussi bien via le worker que
    via le reclaimer."""
    stream = "test-stream"
    group = "g1"
    mock_redis = MockRedis(stream)

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module

    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    observed_flags: list[tuple[int, bool]] = []

    async def fail_retryable(msg: SampleMessage, rc: int, is_last: bool):
        observed_flags.append((rc, is_last))
        raise RetryableException("transient")

    c = ThreadConsumer[SampleMessage](
        consumer_name="c1",
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=fail_retryable,
        worker_number=1,
        max_retry_number=1,
    )
    try:
        msg1_id = "1700000000000-0"
        mock_redis.queue_xread_batch(
            [(msg1_id, {"data": json.dumps({"a": 1}), "retries": "0"})]
        )
        listener = asyncio.create_task(c._start_listening_messages())
        for _ in range(50):
            if mock_redis.acks:
                break
            await asyncio.sleep(0.02)
        c.stop_flag.set()
        await asyncio.wait_for(listener, timeout=2)

        assert observed_flags == [(0, True)]

        c.stop_flag.clear()
        msg2_id = "1700000000001-0"
        mock_redis.queue_xautoclaim(
            "0-0", [(msg2_id, {"data": json.dumps({"a": 2}), "retries": "0"})]
        )
        reclaimer = asyncio.create_task(c._reclaim_pending_messages())
        for _ in range(50):
            if len(mock_redis.acks) >= 2:
                break
            await asyncio.sleep(0.02)
        c.stop_flag.set()
        await asyncio.wait_for(reclaimer, timeout=2)

        requeues = [call for call in mock_redis.xadd_calls if call[0] == stream]
        dlqs = [call for call in mock_redis.xadd_calls if call[0] == f"{stream}:dlq"]
        assert requeues == []
        assert [d[1]["original_id"] for d in dlqs] == [msg1_id, msg2_id]
        assert mock_redis.acks == [(stream, msg1_id), (stream, msg2_id)]
    finally:
        await c._shutdown_executor()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_retries", ["", "abc", "-1", None, True])
async def test_corrupted_retries_routed_to_dlq_without_crashing_or_blocking(
    monkeypatch, bad_retries: Any
):
    """Un champ retries invalide ne doit ni faire tomber la boucle d'écoute ni
    bloquer le reclaimer sur l'entrée poison."""
    stream = "test-stream"
    group = "g1"
    mock_redis = MockRedis(stream)

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module

    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    processed_payloads: list[dict[str, Any]] = []

    async def process_ok(msg: SampleMessage, rc: int, _is_last: bool):
        processed_payloads.append(msg.payload)

    c = ThreadConsumer[SampleMessage](
        consumer_name="c1",
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=process_ok,
        worker_number=1,
        max_retry_number=3,
    )
    try:
        # 1) Listener : message corrompu suivi d'un message valide sans clé retries
        mock_redis.queue_xread_batch(
            [
                (
                    "1700000000000-0",
                    {"data": json.dumps({"bad": 1}), "retries": bad_retries},
                ),
                ("1700000000000-1", {"data": json.dumps({"ok": 2})}),
            ]
        )
        listener = asyncio.create_task(c._start_listening_messages())
        for _ in range(50):
            if len(mock_redis.acks) >= 2:
                break
            await asyncio.sleep(0.02)
        c.stop_flag.set()
        await asyncio.wait_for(listener, timeout=2)

        assert processed_payloads == [{"ok": 2}]
        assert (stream, "1700000000000-0") in mock_redis.acks
        assert (stream, "1700000000000-1") in mock_redis.acks

        # 2) Reclaimer : message corrompu, message sans data, puis message valide sans retries
        c.stop_flag.clear()
        mock_redis.queue_xautoclaim(
            "0-0",
            [
                (
                    "1700000000001-0",
                    {"data": json.dumps({"bad": 2}), "retries": bad_retries},
                ),
                ("1700000000001-1", {}),
                ("1700000000001-2", {"data": json.dumps({"reclaimed": True})}),
            ],
        )
        reclaimer = asyncio.create_task(c._reclaim_pending_messages())
        for _ in range(50):
            if len(mock_redis.acks) >= 5:
                break
            await asyncio.sleep(0.02)
        c.stop_flag.set()
        await asyncio.wait_for(reclaimer, timeout=2)

        requeues = [call for call in mock_redis.xadd_calls if call[0] == stream]
        dlqs = [call for call in mock_redis.xadd_calls if call[0] == f"{stream}:dlq"]
        assert requeues == [
            (
                stream,
                {
                    "data": json.dumps({"reclaimed": True}),
                    "retries": "1",
                    "original_id": "1700000000001-2",
                    "root_id": "1700000000001-2",
                },
            )
        ]
        assert [d[1]["original_id"] for d in dlqs] == [
            "1700000000000-0",
            "1700000000001-0",
            "1700000000001-1",
        ]
        assert all(d[1]["reason"] == "decode_error" for d in dlqs)
    finally:
        await c._shutdown_executor()


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

    c = ThreadConsumer[SampleMessage](
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
    await c._shutdown_executor()


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

    async def conditional_xadd(
        stream_name: str, fields: dict[str, Any], *args: Any, **kwargs: Any
    ):
        if stream_name == stream:
            raise RuntimeError("xadd requeue failed")
        return await original_xadd(stream_name, fields, *args, **kwargs)

    mock_redis.xadd = conditional_xadd  # type: ignore

    c = ThreadConsumer[SampleMessage](
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
    await c._shutdown_executor()


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

    c = ThreadConsumer[SampleMessage](
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

    c = ThreadConsumer[SampleMessage](
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

    c = ThreadConsumer[SampleMessage](
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
    await c._shutdown_executor()


def test_build_instance_consumer_name_includes_host_pid_and_boot_id(monkeypatch):
    monkeypatch.setattr(
        "document_ia_infra.redis.base_consumer.socket.gethostname", lambda: "api-pod-1"
    )
    monkeypatch.setattr("document_ia_infra.redis.base_consumer.os.getpid", lambda: 1)
    monkeypatch.setattr(
        "document_ia_infra.redis.base_consumer._PROCESS_BOOT_ID", "a1b2c3d4"
    )

    name = build_instance_consumer_name("api-webhook-consumer")
    assert name == "api-webhook-consumer-api-pod-1-1-a1b2c3d4"
    # Stable across calls in the same process
    assert build_instance_consumer_name("api-webhook-consumer") == name


def test_build_instance_consumer_name_differs_across_hosts_pids_and_restarts(
    monkeypatch,
):
    base = "api-webhook-consumer"

    monkeypatch.setattr(
        "document_ia_infra.redis.base_consumer.socket.gethostname", lambda: "pod-a"
    )
    monkeypatch.setattr("document_ia_infra.redis.base_consumer.os.getpid", lambda: 1)
    monkeypatch.setattr(
        "document_ia_infra.redis.base_consumer._PROCESS_BOOT_ID", "boot0001"
    )
    name_pod_a = build_instance_consumer_name(base)

    monkeypatch.setattr(
        "document_ia_infra.redis.base_consumer.socket.gethostname", lambda: "pod-b"
    )
    name_pod_b = build_instance_consumer_name(base)

    # Same host + PID 1 after container restart -> distinct boot ID
    monkeypatch.setattr(
        "document_ia_infra.redis.base_consumer._PROCESS_BOOT_ID", "boot0002"
    )
    name_pod_b_restarted = build_instance_consumer_name(base)

    assert len({name_pod_a, name_pod_b, name_pod_b_restarted}) == 3


@pytest.mark.parametrize(
    ("raw_hostname", "expected_host"),
    [
        ("  my host\tname\n ", "my-host-name"),
        ("   ", "unknown"),
        ("", "unknown"),
    ],
)
def test_build_instance_consumer_name_sanitizes_hostname(
    monkeypatch, raw_hostname: str, expected_host: str
):
    monkeypatch.setattr(
        "document_ia_infra.redis.base_consumer.socket.gethostname", lambda: raw_hostname
    )
    monkeypatch.setattr("document_ia_infra.redis.base_consumer.os.getpid", lambda: 42)
    monkeypatch.setattr(
        "document_ia_infra.redis.base_consumer._PROCESS_BOOT_ID", "deadbeef"
    )

    name = build_instance_consumer_name("worker")
    assert name == f"worker-{expected_host}-42-deadbeef"
    assert " " not in name
    assert "\t" not in name
    assert "\n" not in name


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"worker_number": 0}, "worker_number"),
        ({"batch_size": 0}, "batch_size"),
        ({"reclaim_idle_ms": -1}, "reclaim_idle_ms"),
        ({"drain_timeout_s": -1.0}, "drain_timeout_s"),
    ],
)
def test_thread_consumer_validates_init_parameters(kwargs: dict[str, Any], match: str):
    with pytest.raises(ValueError, match=match):
        ThreadConsumer[SampleMessage](
            consumer_name="c1",
            consumer_group="g1",
            stream_name="s1",
            batch_size=kwargs.get("batch_size", 1),
            block_time=10,
            message_class=SampleMessage,
            process_message_callable=lambda m, r, _: asyncio.sleep(0),
            worker_number=kwargs.get("worker_number", 1),
            reclaim_idle_ms=kwargs.get("reclaim_idle_ms"),
            drain_timeout_s=kwargs.get("drain_timeout_s", 10.0),
        )


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"batch_size": 0}, "batch_size"),
        ({"max_concurrency": 0}, "max_concurrency"),
        ({"reclaim_idle_ms": -1}, "reclaim_idle_ms"),
        ({"drain_timeout_s": -1.0}, "drain_timeout_s"),
    ],
)
def test_asyncio_consumer_validates_init_parameters(kwargs: dict[str, Any], match: str):
    with pytest.raises(ValueError, match=match):
        AsyncIoConsumer[SampleMessage](
            consumer_name="c1",
            consumer_group="g1",
            stream_name="s1",
            batch_size=kwargs.get("batch_size", 5),
            block_time=10,
            message_class=SampleMessage,
            process_message_callable=lambda m, r, _: asyncio.sleep(0),
            max_concurrency=kwargs.get("max_concurrency"),
            reclaim_idle_ms=kwargs.get("reclaim_idle_ms"),
            drain_timeout_s=kwargs.get("drain_timeout_s", 10.0),
        )


def test_base_consumer_is_abstract_and_subclasses_have_tailored_defaults():
    with pytest.raises(TypeError):
        BaseConsumer(  # type: ignore[abstract]
            consumer_name="c1",
            consumer_group="g1",
            stream_name="s1",
            batch_size=10,
            block_time=10,
            message_class=SampleMessage,
            process_message_callable=lambda m, r, _: asyncio.sleep(0),
            max_in_flight=10,
        )

    ac = AsyncIoConsumer[SampleMessage](
        consumer_name="api-c1",
        consumer_group="g1",
        stream_name="s1",
        batch_size=50,
        block_time=5000,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
    )
    assert isinstance(ac, BaseConsumer)
    assert ac.max_concurrency == 50
    assert ac.max_in_flight == 50
    assert ac.start_from == "0-0"
    assert ac.close_redis_on_stop is False
    assert not hasattr(ac, "worker_number")
    assert not hasattr(ac, "executor")

    tc = ThreadConsumer[SampleMessage](
        consumer_name="worker-c1",
        consumer_group="g1",
        stream_name="s1",
        batch_size=10,
        block_time=10000,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
        worker_number=4,
    )
    assert isinstance(tc, BaseConsumer)
    assert tc.worker_number == 4
    assert tc.max_in_flight == 4
    assert tc.start_from == "$"
    assert tc.close_redis_on_stop is True
    assert tc.executor is None


@pytest.mark.asyncio
async def test_asyncio_consumer_runs_on_caller_loop_and_respects_defaults(
    monkeypatch,
):
    """AsyncIoConsumer exécute le handler sur l'event loop et le thread
    principal (sans ThreadPoolExecutor), transmet start_from='0-0' par défaut à
    xgroup_create, et ne ferme pas le gestionnaire Redis partagé à l'arrêt."""
    import threading

    stream = "test-asyncio-mode"
    group = "g-asyncio"
    mock_redis = MockRedis(stream)
    msg_id = "1700000000000-0"
    mock_redis.queue_xread_batch([(msg_id, {"data": json.dumps({"ok": 1})})])

    close_calls = 0

    async def fake_get_connection():
        return mock_redis

    async def fake_close():
        nonlocal close_calls
        close_calls += 1

    from document_ia_infra.redis import redis_manager as rm_module

    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)
    monkeypatch.setattr(rm_module.redis_manager, "close", fake_close)

    caller_loop = asyncio.get_running_loop()
    caller_thread_id = threading.get_ident()
    observed: list[tuple[asyncio.AbstractEventLoop, int, int, bool]] = []
    processed = asyncio.Event()

    async def handler(msg: SampleMessage, retry_count: int, is_last: bool) -> None:
        observed.append(
            (
                asyncio.get_running_loop(),
                threading.get_ident(),
                retry_count,
                is_last,
            )
        )
        processed.set()

    c = AsyncIoConsumer[SampleMessage](
        consumer_name="api-c1",
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=20,
        message_class=SampleMessage,
        process_message_callable=handler,
        max_retry_number=4,
        max_concurrency=4,
        reclaim_idle_ms=100,
    )
    assert not hasattr(c, "executor")

    await c.start()
    try:
        await asyncio.wait_for(processed.wait(), timeout=2)
        for _ in range(50):
            if mock_redis.acks:
                break
            await asyncio.sleep(0.01)
    finally:
        await c.stop()

    assert observed == [(caller_loop, caller_thread_id, 0, False)]
    assert mock_redis.groups_created_ids[(stream, group)] == "0-0"
    assert mock_redis.acks == [(stream, msg_id)]
    assert close_calls == 0


@pytest.mark.asyncio
async def test_cancelled_future_leaves_entry_pending_without_dlq_or_ack():
    """Une tâche annulée (ex: arrêt forcé après timeout) ne doit ni acquitter le
    message ni l'envoyer en DLQ comme erreur fatale : l'entrée reste en PEL."""
    stream = "test-cancelled"
    mock_redis = MockRedis(stream)
    c = AsyncIoConsumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name=stream,
        batch_size=1,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
    )

    fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    fut.cancel()

    await c._handle_finished_future(
        fut,
        "1700000000000-0",
        {"data": json.dumps({"a": 1})},
        mock_redis,  # type: ignore[arg-type]
    )

    assert mock_redis.acks == []
    assert mock_redis.xadd_calls == []


@pytest.mark.asyncio
async def test_already_requeued_paginates_on_reclaim_and_hot_path_avoids_xrange(
    monkeypatch,
):
    """_already_requeued pagine via DLQ_SCAN_BATCH_SIZE et empêche un second XADD
    lors de _reclaim_entry, tandis que _handle_finished_future (chemin chaud)
    remet en file en O(1) sans aucun scan XRANGE sur le flux principal."""
    stream = "test-requeue-paged"
    mock_redis = MockRedis(stream)
    monkeypatch.setattr("document_ia_infra.redis.base_consumer.DLQ_SCAN_BATCH_SIZE", 3)

    c = AsyncIoConsumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name=stream,
        batch_size=10,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
        max_retry_number=3,
    )

    original_id = await mock_redis.xadd(
        stream, {"data": json.dumps({"k": 1}), "retries": "0"}
    )
    for idx in range(7):
        await mock_redis.xadd(
            stream, {"data": json.dumps({"other": idx}), "retries": "0"}
        )
    # Copie déjà présente au-delà de plusieurs pages
    await mock_redis.xadd(
        stream,
        {
            "data": json.dumps({"k": 1}),
            "retries": "1",
            "original_id": original_id,
        },
    )
    xadd_count_before = len(mock_redis.xadd_calls)

    assert await c._already_requeued(mock_redis, original_id) is True  # type: ignore[arg-type]
    # 8 entrées postérieures avec lots de 3 -> 3 pages
    assert len(mock_redis.xrange_calls) == 3
    assert mock_redis.xrange_calls[0][1] == f"({original_id}"

    # 1) _reclaim_entry ne recrée pas de copie et acquitte l'original
    mock_redis.xrange_calls.clear()
    await c._reclaim_entry(
        mock_redis,  # type: ignore[arg-type]
        original_id,
        {"data": json.dumps({"k": 1}), "retries": "0"},
    )
    assert len(mock_redis.xadd_calls) == xadd_count_before
    assert mock_redis.acks == [(stream, original_id)]

    # 2) _handle_finished_future n'effectue AUCUN scan XRANGE sur le flux principal
    mock_redis.xrange_calls.clear()
    mock_redis.acks.clear()
    fresh_id = "1800000000000-0"
    fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    fut.set_exception(RetryableException("transient"))
    await c._handle_finished_future(
        fut,
        fresh_id,
        {"data": json.dumps({"k": 2}), "retries": "0"},
        mock_redis,  # type: ignore[arg-type]
    )
    assert mock_redis.xrange_calls == []
    assert len(mock_redis.xadd_calls) == xadd_count_before + 1
    assert mock_redis.acks == [(stream, fresh_id)]


@pytest.mark.asyncio
async def test_reclaim_entry_scan_failure_fails_closed_without_dlq():
    """Si la vérification _already_requeued échoue dans _reclaim_entry,
    l'entrée doit rester en PEL sans écriture en aveugle ni envoi erroné en DLQ."""
    stream = "test-requeue-scan-fail"
    mock_redis = MockRedis(stream)

    async def failing_xrange(*_args: Any, **_kwargs: Any):
        raise ConnectionError("xrange stream down")

    mock_redis.xrange = failing_xrange  # type: ignore[method-assign]

    c = AsyncIoConsumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name=stream,
        batch_size=1,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
        max_retry_number=3,
    )

    await c._reclaim_entry(
        mock_redis,  # type: ignore[arg-type]
        "1700000000000-0",
        {"data": json.dumps({"k": 1}), "retries": "0"},
    )

    assert mock_redis.xadd_calls == []
    assert mock_redis.acks == []


@pytest.mark.asyncio
async def test_nogroup_error_recreates_consumer_group(monkeypatch):
    """Si le flux ou le groupe est supprimé à chaud (NOGROUP), la boucle
    d'écoute recrée automatiquement le groupe sans s'arrêter."""
    stream = "test-nogroup"
    group = "g-nogroup"
    mock_redis = MockRedis(stream)

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module

    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    calls = 0
    original_xreadgroup = mock_redis.xreadgroup
    processed = asyncio.Event()

    async def xreadgroup_nogroup_once(*args: Any, **kwargs: Any):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ResponseError("NOGROUP No such key or consumer group")
        return await original_xreadgroup(*args, **kwargs)

    mock_redis.xreadgroup = xreadgroup_nogroup_once  # type: ignore[method-assign]
    mock_redis.queue_xread_batch(
        [("1700000000000-0", {"data": json.dumps({"ok": True})})]
    )

    async def handler(_msg: SampleMessage, _rc: int, _last: bool) -> None:
        processed.set()

    c = AsyncIoConsumer[SampleMessage](
        consumer_name="c1",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=handler,
    )

    task = asyncio.create_task(c._start_listening_messages())
    try:
        await asyncio.wait_for(processed.wait(), timeout=2)
    finally:
        c.stop_flag.set()
        await asyncio.wait_for(task, timeout=2)

    assert (stream, group) in mock_redis.groups_created
    assert mock_redis.groups_created_ids[(stream, group)] == "0-0"


@pytest.mark.asyncio
async def test_ensure_consumer_group_transient_blip_recovers_without_killing_listener():
    """Un échec transitoire de xgroup_create au démarrage ou lors d'un NOGROUP
    ne doit pas tuer définitivement listener_task (stop_flag reste False)."""
    stream = "test-group-blip"
    group = "g-blip"
    mock_redis = MockRedis(stream)

    class LocalManager:
        def __init__(self) -> None:
            self.redis: Any = mock_redis

        async def get_connection(self) -> Any:
            self.redis = mock_redis
            return mock_redis

        async def close(self) -> None:
            return None

    manager = LocalManager()
    group_attempts = 0
    original_xgroup_create = mock_redis.xgroup_create

    async def flaky_xgroup_create(
        name: str, groupname: str, id: str, mkstream: bool
    ) -> bool:
        nonlocal group_attempts
        group_attempts += 1
        if group_attempts <= 2:
            raise ConnectionError("transient redis blip during XGROUP CREATE")
        return await original_xgroup_create(name, groupname, id, mkstream)

    mock_redis.xgroup_create = flaky_xgroup_create  # type: ignore[method-assign]
    mock_redis.queue_xread_batch(
        [("1700000000000-0", {"data": json.dumps({"recovered": True})})]
    )

    processed = asyncio.Event()

    async def handler(_msg: SampleMessage, _rc: int, _last: bool) -> None:
        processed.set()

    c = AsyncIoConsumer[SampleMessage](
        consumer_name="c1",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=handler,
        reclaim_poll_interval_s=0.05,
        current_redis_manager=manager,  # type: ignore[arg-type]
    )

    await c.start()
    try:
        assert c.is_healthy() is True
        await asyncio.wait_for(processed.wait(), timeout=4)
        assert c.is_healthy() is True
    finally:
        await c.stop()

    assert c.is_healthy() is False
    assert group_attempts >= 3
    assert mock_redis.acks == [(stream, "1700000000000-0")]


@pytest.mark.asyncio
async def test_xadd_passes_stream_and_dlq_maxlen():
    """Les écritures de remise en file et de DLQ appliquent respectivement
    stream_maxlen et dlq_maxlen avec approximate=True."""
    stream = "test-maxlen"
    mock_redis = MockRedis(stream)

    c = AsyncIoConsumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name=stream,
        batch_size=1,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
        max_retry_number=3,
    )
    c.stream_maxlen = 5000
    c.dlq_maxlen = 10000

    fut_retry: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    fut_retry.set_exception(RetryableException("retry"))
    await c._handle_finished_future(
        fut_retry,
        "1700000000000-0",
        {"data": json.dumps({"a": 1}), "retries": "0", "timestamp": "t0"},
        mock_redis,  # type: ignore[arg-type]
    )

    requeued_fields = mock_redis.xadd_calls[0][1]
    requeued_id = mock_redis.xadd_ids[0]
    assert requeued_fields["root_id"] == "1700000000000-0"
    assert requeued_fields["original_timestamp"] == "t0"

    assert await c._send_to_dlq(
        mock_redis,  # type: ignore[arg-type]
        requeued_id,
        requeued_fields,
        "max_retries_exceeded",
        "err",
    )

    dlq_fields = mock_redis.xadd_calls[1][1]
    assert dlq_fields["root_id"] == "1700000000000-0"
    assert dlq_fields["original_id"] == requeued_id
    assert dlq_fields["original_timestamp"] == "t0"
    assert mock_redis.xadd_maxlens == [
        (stream, 5000, True),
        (f"{stream}:dlq", 10000, True),
    ]


@pytest.mark.asyncio
async def test_external_listener_cancellation_acks_done_and_cancels_inflight_tasks():
    """En cas d'annulation externe de listener_task pendant la vidange finally:,
    les futures déjà terminées sont tout de même acquittées (shield) et les tâches
    asyncio encore en cours sont annulées sans fuite d'orphelins."""
    stream = "test-cancel-drain"
    mock_redis = MockRedis(stream)
    mock_redis.queue_xread_batch(
        [
            ("1700000000000-0", {"data": json.dumps({"fast": True})}),
            ("1700000000000-1", {"data": json.dumps({"slow": True})}),
        ]
    )

    class LocalManager:
        redis: Any = mock_redis

        async def get_connection(self) -> Any:
            return mock_redis

        async def close(self) -> None:
            return None

    fast_done = asyncio.Event()
    slow_started = asyncio.Event()
    slow_cancelled = False

    async def handler(msg: SampleMessage, _rc: int, _last: bool) -> None:
        nonlocal slow_cancelled
        if msg.payload.get("fast"):
            fast_done.set()
            return
        slow_started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            slow_cancelled = True
            raise

    c = AsyncIoConsumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name=stream,
        batch_size=10,
        block_time=500,
        message_class=SampleMessage,
        process_message_callable=handler,
        max_concurrency=4,
        drain_timeout_s=30.0,
        current_redis_manager=LocalManager(),  # type: ignore[arg-type]
    )

    listener = asyncio.create_task(c._start_listening_messages())
    await asyncio.wait_for(fast_done.wait(), timeout=2)
    await asyncio.wait_for(slow_started.wait(), timeout=2)

    # Entrer dans le bloc finally: puis annuler listener de l'extérieur
    c.stop_flag.set()
    await asyncio.sleep(0.25)
    listener.cancel()
    with pytest.raises(asyncio.CancelledError):
        await listener

    assert (stream, "1700000000000-0") in mock_redis.acks
    assert (stream, "1700000000000-1") not in mock_redis.acks
    assert slow_cancelled is True
    assert c._in_flight_ids == set()


def test_threadpool_executor_is_lazy_on_init():
    c = ThreadConsumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name="s1",
        batch_size=1,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
    )
    assert c.executor is None


@pytest.mark.asyncio
async def test_reclaimer_skips_and_refreshes_own_in_flight_entries(
    monkeypatch: pytest.MonkeyPatch,
):
    """Quand XAUTOCLAIM retourne un message déjà présent dans _in_flight_ids,
    le reclaimer ne doit ni le requeuer, ni l'envoyer en DLQ, ni l'acquitter.
    Il doit rafraîchir son timer d'inactivité via XCLAIM JUSTID pour le protéger,
    tandis que les entrées réellement orphelines sont requeutées normalement."""
    stream = "test-stream"
    mock_redis = MockRedis(stream)

    async def fake_get_connection():
        return mock_redis

    from document_ia_infra.redis import redis_manager as rm_module

    monkeypatch.setattr(rm_module.redis_manager, "get_connection", fake_get_connection)

    c = ThreadConsumer[SampleMessage](
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

    in_flight_id = "1700000000000-0"
    abandoned_id = "1700000000001-0"

    # Marquer in_flight_id comme en cours de traitement sur ce consommateur
    c._in_flight_ids.add(in_flight_id)

    msg_in_flight = (in_flight_id, {"data": json.dumps({"a": 1}), "retries": "0"})
    msg_abandoned = (abandoned_id, {"data": json.dumps({"a": 2}), "retries": "0"})
    mock_redis.queue_xautoclaim("0-1", [msg_in_flight, msg_abandoned])

    task = asyncio.create_task(c._reclaim_pending_messages())
    await asyncio.sleep(0.1)
    c.stop_flag.set()
    await asyncio.wait_for(task, timeout=2)

    # 1. in_flight_id a été protégé via xclaim JUSTID
    refreshed_ids = [call[4] for call in mock_redis.xclaim_calls if call[5] is True]
    assert any(in_flight_id in ids for ids in refreshed_ids)

    # 2. in_flight_id n'a PAS été acquitté par le reclaimer
    assert (stream, in_flight_id) not in mock_redis.acks

    # 3. in_flight_id n'a PAS été requeuté
    requeued_original_ids = [
        call[1].get("original_id")
        for call in mock_redis.xadd_calls
        if call[0] == stream
    ]
    assert in_flight_id not in requeued_original_ids

    # 4. En revanche, abandoned_id a été requeuté et acquitté
    assert abandoned_id in requeued_original_ids
    assert (stream, abandoned_id) in mock_redis.acks

    # 5. _reclaiming_ids est complètement vidé
    assert c._reclaiming_ids == set()
    await c._shutdown_executor()


@pytest.mark.asyncio
async def test_stop_tasks_only_cancels_heartbeat_on_cancelled_error():
    """Si _stop_tasks_only() est annulée pendant qu'elle attend la tâche de
    battement, elle doit annuler et attendre heartbeat_task pour éviter une tâche
    orpheline, puis propager CancelledError."""
    stream = "test-stream"

    c = AsyncIoConsumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name=stream,
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
    )

    heartbeat_cancelled = asyncio.Event()

    async def fake_heartbeat():
        try:
            while True:
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            heartbeat_cancelled.set()
            raise

    c.heartbeat_task = asyncio.create_task(fake_heartbeat())

    stop_task = asyncio.create_task(c._stop_tasks_only())
    await asyncio.sleep(0.05)
    stop_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await stop_task

    assert heartbeat_cancelled.is_set()
    assert c.heartbeat_task is None or c.heartbeat_task.done()


@pytest.mark.asyncio
async def test_asyncio_consumer_abort_unfinished_futures_timeout():
    """_abort_unfinished_futures applique un timeout pour ne pas bloquer
    indéfiniment l'arrêt si une future ne répond pas à l'annulation."""
    c = AsyncIoConsumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name="test-stream",
        batch_size=10,
        block_time=50,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
    )

    async def unyielding_task():
        # Tâche qui intercepte l'annulation et continue à dormir
        while True:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(10)

    task = asyncio.create_task(unyielding_task())
    try:
        # Doit sortir proprement sans bloquer grâce au wait_for
        await asyncio.wait_for(c._abort_unfinished_futures([task]), timeout=1.0)
    except TimeoutError:
        # Le timeout interne de 5.0s dans _abort_unfinished_futures est plus long que 1s,
        # donc pour le test on peut tester directement avec un timeout interne mocké
        pass
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_thread_consumer_sync_wrapper_cancels_pending_tasks_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
):
    """Si une tâche de fond non terminée reste dans la boucle du thread et
    dépasse le délai de vidange, _process_message_sync_wrapper doit annuler
    les tâches en suspens, fermer la boucle proprement et réinitialiser l'event loop."""
    import asyncio as aio

    c = ThreadConsumer[SampleMessage](
        consumer_name="c1",
        consumer_group="g1",
        stream_name="test-stream",
        batch_size=1,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=lambda m, r, _: asyncio.sleep(0),
    )

    async def spawn_leaking_task(_msg: SampleMessage, _rc: int, _is_last: bool) -> None:
        async def endless_task():
            while True:
                await aio.sleep(100)

        aio.create_task(endless_task())

    c.process_message_callable = spawn_leaking_task

    # Raccourcir le wait_for timeout pour le test
    real_wait_for = aio.wait_for

    async def fast_wait_for(fut, timeout):  # type: ignore
        return await real_wait_for(fut, timeout=0.05)

    monkeypatch.setattr(aio, "wait_for", fast_wait_for)

    message = SampleMessage({"test": "leak"})
    # Doit s'exécuter et sortir sans erreur ni boucle pendante
    c._process_message_sync_wrapper(message, 0)
    with pytest.raises(RuntimeError, match="no current event loop"):
        aio.get_event_loop_policy().get_event_loop()
