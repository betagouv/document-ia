import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy.exc import OperationalError

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
        return SampleMessage(json.loads(data))


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
    name = f"test-worker-ack:{uuid4()}"
    try:
        yield name
    finally:
        await redis_client.delete(name, f"{name}:dlq")


def make_consumer(stream: str, group: str) -> Consumer[SampleMessage]:
    async def process_noop(
        message: SampleMessage, retry_count: int, is_last: bool
    ) -> None:
        return None

    return Consumer[SampleMessage](
        consumer_name="test-worker",
        consumer_group=group,
        stream_name=stream,
        batch_size=1,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=process_noop,
        worker_number=1,
        max_retry_number=3,
    )


async def wait_until(
    predicate: Callable[[], Awaitable[bool]], timeout: float = 2.0
) -> None:
    async with asyncio.timeout(timeout):
        while not await predicate():
            await asyncio.sleep(0.01)


async def pending_count(redis: Redis, stream: str, group: str) -> int:
    info = await redis.xpending(stream, group)
    return info["pending"] if isinstance(info, dict) else info.pending


async def read_message(
    redis: Redis, stream: str, group: str, data: str, retries: str = "0"
) -> tuple[str, dict[str, Any]]:
    await redis.xadd(stream, {"data": data, "retries": retries})
    await redis.xgroup_create(stream, group, id="0-0")
    response = await redis.xreadgroup(
        groupname=group,
        consumername="original-worker",
        streams={stream: ">"},
        count=1,
    )
    assert response is not None
    return response[0][1][0]


@pytest.mark.asyncio
async def test_worker_acknowledges_success(redis_client: Redis, stream: str) -> None:
    group = "worker-group"
    msg_id, fields = await read_message(
        redis_client, stream, group, json.dumps({"payload": "ok"})
    )
    consumer = make_consumer(stream, group)
    future = asyncio.get_running_loop().create_future()
    future.set_result(None)

    await consumer._handle_finished_future(future, msg_id, fields, redis_client)

    assert await pending_count(redis_client, stream, group) == 0
    consumer.executor.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("dlq_available", [True, False])
@pytest.mark.parametrize("failure_kind", ["database", "max_retries"])
async def test_worker_terminal_failure_requires_dlq_before_ack(
    redis_client: Redis,
    stream: str,
    monkeypatch: pytest.MonkeyPatch,
    dlq_available: bool,
    failure_kind: str,
) -> None:
    group = "worker-group"
    msg_id, fields = await read_message(
        redis_client,
        stream,
        group,
        json.dumps({"payload": failure_kind}),
        retries="2" if failure_kind == "max_retries" else "0",
    )
    consumer = make_consumer(stream, group)
    future = asyncio.get_running_loop().create_future()
    if failure_kind == "database":
        error: Exception = OperationalError(
            "SELECT 1", {}, ConnectionError("database unavailable")
        )
    else:
        error = RetryableException("last attempt failed")
    future.set_exception(error)
    operations: list[str] = []
    original_eval = redis_client.eval
    original_xack = redis_client.xack

    async def record_eval(script: str, numkeys: int, *args: Any) -> Any:
        # DLQ retention targets the DLQ stream as its single key.
        operations.append(f"xadd:{args[0]}")
        if not dlq_available:
            raise ConnectionError("DLQ unavailable")
        return await original_eval(script, numkeys, *args)

    async def record_xack(stream_name: str, group_name: str, msg_id: str) -> Any:
        operations.append(f"xack:{stream_name}")
        return await original_xack(stream_name, group_name, msg_id)

    monkeypatch.setattr(redis_client, "eval", record_eval)
    monkeypatch.setattr(redis_client, "xack", record_xack)

    await consumer._handle_finished_future(future, msg_id, fields, redis_client)

    expected_pending = 0 if dlq_available else 1
    assert await pending_count(redis_client, stream, group) == expected_pending
    assert await redis_client.xlen(f"{stream}:dlq") == (1 if dlq_available else 0)
    if dlq_available:
        assert operations == [f"xadd:{stream}:dlq", f"xack:{stream}"]
    consumer.executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_worker_requeue_and_dlq_failures_leave_message_pending(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = "worker-group"
    msg_id, fields = await read_message(
        redis_client, stream, group, json.dumps({"payload": "requeue"})
    )
    consumer = make_consumer(stream, group)
    future = asyncio.get_running_loop().create_future()
    future.set_exception(RetryableException("temporary failure"))
    operations: list[str] = []

    async def fail_eval(script: str, numkeys: int, *args: Any) -> Any:
        # Both the requeue (stream) and DLQ retention (dlq stream) go via eval.
        operations.append(f"xadd:{args[0]}")
        raise ConnectionError(f"Redis write unavailable for {args[0]}")

    async def record_ack(stream_name: str, group_name: str, msg_id: str) -> Any:
        operations.append(f"xack:{stream_name}")
        return 1

    monkeypatch.setattr(redis_client, "eval", fail_eval)
    monkeypatch.setattr(redis_client, "xack", record_ack)

    await consumer._handle_finished_future(future, msg_id, fields, redis_client)

    assert operations == [f"xadd:{stream}", f"xadd:{stream}:dlq"]
    assert await pending_count(redis_client, stream, group) == 1
    assert await redis_client.xlen(stream) == 1
    assert await redis_client.xlen(f"{stream}:dlq") == 0
    consumer.executor.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("dlq_available", [True, False])
async def test_worker_decode_failure_requires_dlq_before_ack(
    redis_client: Redis,
    stream: str,
    monkeypatch: pytest.MonkeyPatch,
    dlq_available: bool,
) -> None:
    group = "worker-group"
    await redis_client.xgroup_create(stream, group, id="$", mkstream=True)
    await redis_client.xadd(stream, {"data": "{invalid-json}", "retries": "0"})
    consumer = make_consumer(stream, group)

    async def get_connection() -> Redis:
        return redis_client

    from document_ia_infra.redis import redis_manager as redis_manager_module

    monkeypatch.setattr(
        redis_manager_module.redis_manager, "get_connection", get_connection
    )
    dlq_attempted = asyncio.Event()
    original_eval = redis_client.eval

    async def record_dlq_attempt(script: str, numkeys: int, *args: Any) -> Any:
        if args and args[0] == f"{stream}:dlq":
            dlq_attempted.set()
            if not dlq_available:
                raise ConnectionError("DLQ unavailable")
        return await original_eval(script, numkeys, *args)

    monkeypatch.setattr(redis_client, "eval", record_dlq_attempt)
    original_xreadgroup = redis_client.xreadgroup
    next_read_started = asyncio.Event()
    read_count = 0

    async def record_read(*args: Any, **kwargs: Any) -> Any:
        nonlocal read_count
        read_count += 1
        if read_count >= 2:
            next_read_started.set()
        return await original_xreadgroup(*args, **kwargs)

    monkeypatch.setattr(redis_client, "xreadgroup", record_read)
    listener = asyncio.create_task(consumer._start_listening_messages())
    try:
        await asyncio.wait_for(dlq_attempted.wait(), timeout=2)
        await asyncio.wait_for(next_read_started.wait(), timeout=2)

        async def reached_expected_state() -> bool:
            pending = await pending_count(redis_client, stream, group)
            dlq_length = await redis_client.xlen(f"{stream}:dlq")
            if dlq_available:
                return pending == 0 and dlq_length == 1
            return pending == 1 and dlq_length == 0

        await wait_until(reached_expected_state)
    finally:
        consumer.stop_flag.set()
        await asyncio.wait_for(listener, timeout=2)
        consumer.executor.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("dlq_available", [True, False])
async def test_worker_reclaimed_message_requires_dlq_before_ack(
    redis_client: Redis,
    stream: str,
    monkeypatch: pytest.MonkeyPatch,
    dlq_available: bool,
) -> None:
    group = "worker-group"
    await read_message(
        redis_client,
        stream,
        group,
        json.dumps({"payload": "reclaimed"}),
        retries="3",
    )
    consumer = make_consumer(stream, group)

    async def get_connection() -> Redis:
        return redis_client

    from document_ia_infra.redis import redis_manager as redis_manager_module

    monkeypatch.setattr(
        redis_manager_module.redis_manager, "get_connection", get_connection
    )
    monkeypatch.setattr(
        "document_ia_infra.redis.consumer.RECLAIM_IDLE_MS",
        0,
    )
    dlq_attempted = asyncio.Event()
    original_eval = redis_client.eval

    async def record_dlq_attempt(script: str, numkeys: int, *args: Any) -> Any:
        if args and args[0] == f"{stream}:dlq":
            dlq_attempted.set()
            if not dlq_available:
                raise ConnectionError("DLQ unavailable")
        return await original_eval(script, numkeys, *args)

    monkeypatch.setattr(redis_client, "eval", record_dlq_attempt)
    original_xautoclaim = redis_client.xautoclaim
    next_claim_started = asyncio.Event()
    claim_count = 0

    async def record_claim(*args: Any, **kwargs: Any) -> Any:
        nonlocal claim_count
        claim_count += 1
        if claim_count >= 2:
            next_claim_started.set()
        return await original_xautoclaim(*args, **kwargs)

    monkeypatch.setattr(redis_client, "xautoclaim", record_claim)
    reclaimer = asyncio.create_task(consumer._reclaim_pending_messages())
    try:
        await asyncio.wait_for(dlq_attempted.wait(), timeout=2)
        await asyncio.wait_for(next_claim_started.wait(), timeout=2)

        async def reached_expected_state() -> bool:
            pending = await pending_count(redis_client, stream, group)
            dlq_length = await redis_client.xlen(f"{stream}:dlq")
            if dlq_available:
                return pending == 0 and dlq_length == 1
            return pending == 1 and dlq_length == 0

        await wait_until(reached_expected_state)
    finally:
        consumer.stop_flag.set()
        await asyncio.wait_for(reclaimer, timeout=2)
        consumer.executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_reclaim_succession_consumes_one_attempt_per_step(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Succession traitement initial, récupération puis épuisement (issue #111) :
    chaque étape consomme exactement une tentative et le seuil d'épuisement
    est le même que celui du chemin d'erreur du worker."""
    group = "worker-group"
    consumer = make_consumer(stream, group)

    # Étape 1 : traitement initial (retries=0), échec réessayable -> requeue retries=1
    first_id, first_fields = await read_message(
        redis_client, stream, group, json.dumps({"payload": "succession"})
    )
    future = asyncio.get_running_loop().create_future()
    future.set_exception(RetryableException("initial attempt failed"))
    await consumer._handle_finished_future(future, first_id, first_fields, redis_client)
    assert await pending_count(redis_client, stream, group) == 0

    # Étape 2 : un worker relit la nouvelle entrée puis s'arrête sans ACK ;
    # la récupération consomme une seule tentative -> requeue retries=2
    response = await redis_client.xreadgroup(
        groupname=group,
        consumername="original-worker",
        streams={stream: ">"},
        count=1,
    )
    second_id, second_fields = response[0][1][0]
    assert second_fields["retries"] == "1"

    async def get_connection() -> Redis:
        return redis_client

    from document_ia_infra.redis import redis_manager as redis_manager_module

    monkeypatch.setattr(
        redis_manager_module.redis_manager, "get_connection", get_connection
    )
    monkeypatch.setattr("document_ia_infra.redis.consumer.RECLAIM_IDLE_MS", 0)

    reclaimer = asyncio.create_task(consumer._reclaim_pending_messages())
    try:

        async def reclaimed() -> bool:
            return await pending_count(redis_client, stream, group) == 0

        await wait_until(reclaimed)
    finally:
        consumer.stop_flag.set()
        await asyncio.wait_for(reclaimer, timeout=2)

    # Étape 3 : traitement de la dernière tentative (retries=2), échec
    # réessayable -> épuisement -> DLQ après conservation confirmée
    response = await redis_client.xreadgroup(
        groupname=group,
        consumername="original-worker",
        streams={stream: ">"},
        count=1,
    )
    third_id, third_fields = response[0][1][0]
    assert third_fields["retries"] == "2"

    future = asyncio.get_running_loop().create_future()
    future.set_exception(RetryableException("last attempt failed"))
    await consumer._handle_finished_future(future, third_id, third_fields, redis_client)

    assert await pending_count(redis_client, stream, group) == 0
    assert await redis_client.xlen(f"{stream}:dlq") == 1
    dlq_entries = await redis_client.xrange(f"{stream}:dlq")
    assert dlq_entries[0][1]["original_id"] == third_id
    assert dlq_entries[0][1]["reason"] == "max_retries_exceeded"

    # l'escalade des tentatives est strictement unitaire sur toute la succession
    stream_entries = await redis_client.xrange(stream)
    retries_sequence = [entry_fields["retries"] for _id, entry_fields in stream_entries]
    assert retries_sequence == ["0", "1", "2"]
    consumer.executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_reclaim_after_dlq_retention_terminates_without_duplicate(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Conservation DLQ confirmée puis ACK en échec : une nouvelle récupération
    termine l'entrée d'origine sans conserver une deuxième copie (issue #111)."""
    group = "worker-group"
    msg_id, fields = await read_message(
        redis_client,
        stream,
        group,
        json.dumps({"payload": "reclaim-after-retention"}),
        retries="2",
    )
    consumer = make_consumer(stream, group)

    async def get_connection() -> Redis:
        return redis_client

    from document_ia_infra.redis import redis_manager as redis_manager_module

    monkeypatch.setattr(
        redis_manager_module.redis_manager, "get_connection", get_connection
    )
    monkeypatch.setattr("document_ia_infra.redis.consumer.RECLAIM_IDLE_MS", 0)

    # le premier ACK échoue : la conservation DLQ est confirmée mais
    # l'entrée d'origine reste en attente et subit une nouvelle récupération
    ack_failures = 1
    original_xack = redis_client.xack

    async def flaky_xack(stream_name: str, group_name: str, msg_id: str) -> Any:
        nonlocal ack_failures
        if ack_failures > 0:
            ack_failures -= 1
            raise ConnectionError("ack unavailable")
        return await original_xack(stream_name, group_name, msg_id)

    monkeypatch.setattr(redis_client, "xack", flaky_xack)

    reclaimer = asyncio.create_task(consumer._reclaim_pending_messages())
    try:

        async def terminated() -> bool:
            return await pending_count(redis_client, stream, group) == 0

        await wait_until(terminated, timeout=5.0)
    finally:
        consumer.stop_flag.set()
        await asyncio.wait_for(reclaimer, timeout=5)

    assert await redis_client.xlen(f"{stream}:dlq") == 1
    dlq_entries = await redis_client.xrange(f"{stream}:dlq")
    assert dlq_entries[0][1]["original_id"] == msg_id
    consumer.executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_dlq_retention_is_idempotent_despite_history(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La conservation DLQ est exactement-une-fois même avec un historique
    important : une deuxième conservation pour le même « original_id » ne
    crée pas de doublon, quel que soit le nombre d'entrées antérieures."""
    group = "worker-group"
    dlq = f"{stream}:dlq"

    # 200 entrées DLQ antérieures au message d'origine
    for index in range(200):
        await redis_client.xadd(
            dlq, {"original_id": f"stale-{index}", "data": "x"}, id=f"{index + 1}-0"
        )

    msg_id = await redis_client.xadd(stream, {"data": json.dumps({"payload": "scan"})})
    consumer = make_consumer(stream, group)

    fields = {"data": json.dumps({"payload": "scan"}), "retries": "2"}
    assert await consumer._send_to_dlq(
        redis_client, msg_id, fields, "max_retries_exceeded"
    )
    # deuxième conservation : détectée comme doublon, aucune nouvelle ligne
    assert await consumer._send_to_dlq(
        redis_client, msg_id, fields, "max_retries_exceeded"
    )

    assert await redis_client.xlen(dlq) == 201
    consumer.executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_dlq_retention_detects_same_millisecond_entry(
    redis_client: Redis, stream: str
) -> None:
    """Séquences indépendantes par flux : une conservation DLQ de la même
    milliseconde que le message d'origine peut précéder son identifiant
    (source T-5, DLQ T-0) ; elle doit rester détectée après un ACK en échec."""
    group = "worker-group"
    dlq = f"{stream}:dlq"

    # six entrées source dans la même milliseconde ; la dernière porte T-5
    for seq in range(6):
        await redis_client.xadd(stream, {"data": "x"}, id=f"12345-{seq}")
    msg_id = "12345-5"

    # conservation DLQ de la même milliseconde, séquence indépendante
    await redis_client.xadd(
        dlq,
        {"original_id": msg_id, "data": "x", "reason": "decode_error"},
        id="12345-0",
    )

    consumer = make_consumer(stream, group)

    # la conservation existante est détectée malgré l'inversion de séquence :
    # aucune nouvelle écriture DLQ
    assert await consumer._send_to_dlq(
        redis_client, msg_id, {"data": "x", "retries": "0"}, "decode_error"
    )
    assert await redis_client.xlen(dlq) == 1
    consumer.executor.shutdown(wait=True)
