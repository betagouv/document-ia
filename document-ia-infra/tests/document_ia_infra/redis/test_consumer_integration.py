import asyncio
import json
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy.exc import OperationalError

from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.redis.consumer import (
    AsyncIoConsumer,
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


def make_consumer(stream: str, group: str) -> ThreadConsumer[SampleMessage]:
    async def process_noop(
        message: SampleMessage, retry_count: int, is_last: bool
    ) -> None:
        return None

    return ThreadConsumer[SampleMessage](
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
    await consumer._shutdown_executor()


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
    await consumer._shutdown_executor()


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
    await consumer._shutdown_executor()


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
        await consumer._shutdown_executor()


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
        retries="2",
    )
    consumer = make_consumer(stream, group)

    async def get_connection() -> Redis:
        return redis_client

    from document_ia_infra.redis import redis_manager as redis_manager_module

    monkeypatch.setattr(
        redis_manager_module.redis_manager, "get_connection", get_connection
    )
    monkeypatch.setattr(
        "document_ia_infra.redis.base_consumer.RECLAIM_IDLE_MS",
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
        if dlq_available:
            dlq_entries = await redis_client.xrange(f"{stream}:dlq")
            assert dlq_entries[0][1]["retries"] == "2"
    finally:
        consumer.stop_flag.set()
        await asyncio.wait_for(reclaimer, timeout=2)
        await consumer._shutdown_executor()


@pytest.mark.asyncio
async def test_reclaim_succession_consumes_one_attempt_per_step(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Succession traitement initial, récupération puis épuisement (issue #111) :
    chaque étape consomme exactement une tentative et le seuil d'épuisement
    est le même que celui du chemin d'erreur du worker."""
    group = "worker-group"
    consumer = make_consumer(stream, group)
    try:
        # Étape 1 : traitement initial (retries=0), échec réessayable -> requeue retries=1
        first_id, first_fields = await read_message(
            redis_client, stream, group, json.dumps({"payload": "succession"})
        )
        future = asyncio.get_running_loop().create_future()
        future.set_exception(RetryableException("initial attempt failed"))
        await consumer._handle_finished_future(
            future, first_id, first_fields, redis_client
        )
        assert await pending_count(redis_client, stream, group) == 0

        # Étape 2 : un worker relit la nouvelle entrée puis s'arrête sans ACK ;
        # la récupération consomme une seule tentative -> requeue retries=2
        response = await redis_client.xreadgroup(
            groupname=group,
            consumername="original-worker",
            streams={stream: ">"},
            count=1,
        )
        _second_id, second_fields = response[0][1][0]
        assert second_fields["retries"] == "1"

        async def get_connection() -> Redis:
            return redis_client

        from document_ia_infra.redis import redis_manager as redis_manager_module

        monkeypatch.setattr(
            redis_manager_module.redis_manager, "get_connection", get_connection
        )
        monkeypatch.setattr("document_ia_infra.redis.base_consumer.RECLAIM_IDLE_MS", 0)

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
        await consumer._handle_finished_future(
            future, third_id, third_fields, redis_client
        )

        assert await pending_count(redis_client, stream, group) == 0
        assert await redis_client.xlen(f"{stream}:dlq") == 1
        dlq_entries = await redis_client.xrange(f"{stream}:dlq")
        assert dlq_entries[0][1]["original_id"] == third_id
        assert dlq_entries[0][1]["reason"] == "max_retries_exceeded"
        assert dlq_entries[0][1]["retries"] == "2"

        # l'escalade des tentatives est strictement unitaire sur toute la succession
        stream_entries = await redis_client.xrange(stream)
        retries_sequence = [
            entry_fields["retries"] for _id, entry_fields in stream_entries
        ]
        assert retries_sequence == ["0", "1", "2"]
    finally:
        await consumer._shutdown_executor()


@pytest.mark.asyncio
async def test_reclaim_after_dlq_retention_terminates_without_duplicate(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Conservation DLQ confirmée puis ACK en échec : une nouvelle récupération
    termine l'entrée d'origine sans conserver une deuxième copie (issue #111)."""
    group = "worker-group"
    msg_id, _fields = await read_message(
        redis_client,
        stream,
        group,
        json.dumps({"payload": "reclaim-after-retention"}),
        retries="2",
    )
    consumer = make_consumer(stream, group)
    try:

        async def get_connection() -> Redis:
            return redis_client

        from document_ia_infra.redis import redis_manager as redis_manager_module

        monkeypatch.setattr(
            redis_manager_module.redis_manager, "get_connection", get_connection
        )
        monkeypatch.setattr("document_ia_infra.redis.base_consumer.RECLAIM_IDLE_MS", 0)

        # le premier ACK échoue : la conservation DLQ est confirmée mais
        # l'entrée d'origine reste en attente et subit une nouvelle récupération
        ack_failures = 1
        original_xack = redis_client.xack

        async def flaky_xack(stream_name: str, group_name: str, mid: str) -> Any:
            nonlocal ack_failures
            if ack_failures > 0:
                ack_failures -= 1
                raise ConnectionError("ack unavailable")
            return await original_xack(stream_name, group_name, mid)

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
        assert dlq_entries[0][1]["retries"] == "2"
    finally:
        await consumer._shutdown_executor()


@pytest.mark.asyncio
async def test_reclaim_after_zero_retry_dlq_retention_terminates_without_requeue(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Échec terminal dès retries=0 (ex: not_retryable_error), conservation DLQ
    confirmée puis ACK en échec : le reclaimer acquitte l'entrée sans la remettre
    dans le flux principal ni la dupliquer dans la DLQ."""
    group = "worker-group"
    msg_id, fields = await read_message(
        redis_client,
        stream,
        group,
        json.dumps({"payload": "fatal-on-first-attempt"}),
        retries="0",
    )
    consumer = make_consumer(stream, group)
    try:
        original_xack = redis_client.xack
        ack_failures = 1

        async def fail_first_ack(stream_name: str, group_name: str, mid: str) -> Any:
            nonlocal ack_failures
            if ack_failures > 0:
                ack_failures -= 1
                raise ConnectionError("ack failed after terminal DLQ write")
            return await original_xack(stream_name, group_name, mid)

        monkeypatch.setattr(redis_client, "xack", fail_first_ack)

        # Le worker échoue sur une erreur non réessayable : DLQ écrite mais ACK en échec
        future = asyncio.get_running_loop().create_future()
        future.set_exception(ValueError("fatal business error"))
        await consumer._handle_finished_future(future, msg_id, fields, redis_client)

        assert await pending_count(redis_client, stream, group) == 1
        assert await redis_client.xlen(f"{stream}:dlq") == 1

        async def get_connection() -> Redis:
            return redis_client

        from document_ia_infra.redis import redis_manager as redis_manager_module

        monkeypatch.setattr(
            redis_manager_module.redis_manager, "get_connection", get_connection
        )
        monkeypatch.setattr("document_ia_infra.redis.base_consumer.RECLAIM_IDLE_MS", 0)

        reclaimer = asyncio.create_task(consumer._reclaim_pending_messages())
        try:

            async def terminated() -> bool:
                return await pending_count(redis_client, stream, group) == 0

            await wait_until(terminated, timeout=5.0)
        finally:
            consumer.stop_flag.set()
            await asyncio.wait_for(reclaimer, timeout=5)

        # aucune remise en file sur le flux source et aucune copie supplémentaire en DLQ
        assert await redis_client.xlen(stream) == 1
        assert await redis_client.xlen(f"{stream}:dlq") == 1
        dlq_entries = await redis_client.xrange(f"{stream}:dlq")
        assert dlq_entries[0][1]["original_id"] == msg_id
        assert dlq_entries[0][1]["reason"] == "not_retryable_error"
    finally:
        await consumer._shutdown_executor()


@pytest.mark.asyncio
async def test_dlq_retention_scan_skips_history_older_than_original(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La détection d'entrée déjà conservée démarre au début de la milliseconde
    du message d'origine (<source_ms>-0) : l'historique antérieur de la DLQ
    n'est pas chargé, même lorsque la séquence du message source est > 0."""
    group = "worker-group"
    dlq = f"{stream}:dlq"

    # 200 entrées DLQ antérieures au message d'origine (identifiants explicites
    # pour garantir un ordre strict indépendant de l'horloge)
    for index in range(200):
        await redis_client.xadd(
            dlq, {"original_id": f"stale-{index}", "data": "x"}, id=f"{index + 1}-0"
        )

    # Deux messages dans la même milliseconde sur le flux source afin d'avoir seq > 0
    first_id = await redis_client.xadd(
        stream, {"data": json.dumps({"payload": "warmup"})}
    )
    source_ms = first_id.split("-")[0]
    msg_id = await redis_client.xadd(
        stream,
        {"data": json.dumps({"payload": "scan"})},
        id=f"{source_ms}-3",
    )
    consumer = make_consumer(stream, group)
    try:
        scans: list[tuple[str, int]] = []
        original_xrange = redis_client.xrange

        async def spying_xrange(
            name: str, min: str = "-", max: str = "+", count: int | None = None
        ) -> Any:
            result = await original_xrange(name, min, max, count)
            if name == dlq:
                scans.append((str(min), len(result)))
            return result

        monkeypatch.setattr(redis_client, "xrange", spying_xrange)

        fields = {"data": json.dumps({"payload": "scan"}), "retries": "2"}
        assert await consumer._send_to_dlq(
            redis_client, msg_id, fields, "max_retries_exceeded"
        )
        # deuxième conservation : détectée comme doublon par le parcours borné
        assert await consumer._send_to_dlq(
            redis_client, msg_id, fields, "max_retries_exceeded"
        )

        # chaque parcours démarre à <source_ms>-0 et ignore les 200 entrées antérieures
        expected_min = f"{source_ms}-0"
        assert scans == [(expected_min, 0), (expected_min, 1)]
        assert await redis_client.xlen(dlq) == 201
    finally:
        await consumer._shutdown_executor()


@pytest.mark.asyncio
async def test_dlq_retention_scan_includes_source_millisecond(
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
    try:
        # la conservation existante est détectée malgré l'inversion de séquence :
        # aucune nouvelle écriture DLQ
        assert await consumer._send_to_dlq(
            redis_client, msg_id, {"data": "x", "retries": "0"}, "decode_error"
        )
        assert await redis_client.xlen(dlq) == 1
    finally:
        await consumer._shutdown_executor()


@pytest.mark.asyncio
async def test_dlq_scan_failure_fails_closed_against_real_redis(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si xrange sur la DLQ échoue temporairement alors que l'entrée est déjà
    conservée, le consumer échoue en mode fermé : pas de doublon DLQ ni d'ACK."""
    group = "worker-group"
    msg_id, fields = await read_message(
        redis_client,
        stream,
        group,
        json.dumps({"payload": "fail-closed"}),
        retries="0",
    )
    consumer = make_consumer(stream, group)
    try:
        # L'entrée est déjà présente en DLQ (suite à un ACK précédemment échoué)
        assert await consumer._send_to_dlq(
            redis_client, msg_id, fields, "not_retryable_error", "initial"
        )
        assert await redis_client.xlen(f"{stream}:dlq") == 1

        original_xrange = redis_client.xrange

        async def failing_dlq_xrange(
            name: str, min: str = "-", max: str = "+", count: int | None = None
        ) -> Any:
            if name == f"{stream}:dlq":
                raise ConnectionError("DLQ scan unavailable")
            return await original_xrange(name, min, max, count)

        monkeypatch.setattr(redis_client, "xrange", failing_dlq_xrange)

        # _send_to_dlq refuse d'écrire à l'aveugle : aucun doublon ajouté
        assert (
            await consumer._send_to_dlq(
                redis_client, msg_id, fields, "not_retryable_error", "retry"
            )
            is False
        )
        assert await redis_client.xlen(f"{stream}:dlq") == 1
        assert await pending_count(redis_client, stream, group) == 1
    finally:
        await consumer._shutdown_executor()


@pytest.mark.asyncio
async def test_reclaim_corrupted_retries_routes_to_dlq_and_advances_cursor(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une entrée en attente avec un champ retries corrompu part en DLQ
    (decode_error), est acquittée et ne bloque pas la récupération des messages
    suivants dans la PEL."""
    group = "worker-group"
    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    poison_id = await redis_client.xadd(
        stream, {"data": json.dumps({"payload": "poison"}), "retries": "not-an-int"}
    )
    valid_id = await redis_client.xadd(
        stream, {"data": json.dumps({"payload": "valid"}), "retries": "0"}
    )
    # Les deux messages sont lus sans ACK
    response = await redis_client.xreadgroup(
        groupname=group,
        consumername="crashed-worker",
        streams={stream: ">"},
        count=2,
    )
    assert len(response[0][1]) == 2
    assert await pending_count(redis_client, stream, group) == 2

    consumer = make_consumer(stream, group)
    try:

        async def get_connection() -> Redis:
            return redis_client

        from document_ia_infra.redis import redis_manager as redis_manager_module

        monkeypatch.setattr(
            redis_manager_module.redis_manager, "get_connection", get_connection
        )
        monkeypatch.setattr("document_ia_infra.redis.base_consumer.RECLAIM_IDLE_MS", 0)

        reclaimer = asyncio.create_task(consumer._reclaim_pending_messages())
        try:

            async def drained() -> bool:
                return await pending_count(redis_client, stream, group) == 0

            await wait_until(drained, timeout=5.0)
        finally:
            consumer.stop_flag.set()
            await asyncio.wait_for(reclaimer, timeout=5)

        dlq_entries = await redis_client.xrange(f"{stream}:dlq")
        assert len(dlq_entries) == 1
        assert dlq_entries[0][1]["original_id"] == poison_id
        assert dlq_entries[0][1]["reason"] == "decode_error"

        stream_entries = await redis_client.xrange(stream)
        assert len(stream_entries) == 3
        assert stream_entries[-1][0] != valid_id
        assert stream_entries[-1][1]["retries"] == "1"
    finally:
        await consumer._shutdown_executor()


@pytest.mark.asyncio
async def test_dlq_retention_scan_paginates_on_real_redis(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pagination réelle avec Redis : retrouve une entrée DLQ au-delà de plusieurs
    pages bornées par DLQ_SCAN_BATCH_SIZE."""
    group = "worker-group"
    dlq = f"{stream}:dlq"
    monkeypatch.setattr("document_ia_infra.redis.base_consumer.DLQ_SCAN_BATCH_SIZE", 5)

    msg_id = await redis_client.xadd(stream, {"data": json.dumps({"payload": "paged"})})
    for idx in range(12):
        await redis_client.xadd(dlq, {"original_id": f"other-{idx}", "data": "x"})
    await redis_client.xadd(dlq, {"original_id": msg_id, "data": "target"})

    consumer = make_consumer(stream, group)
    try:
        batch_sizes: list[int] = []
        original_xrange = redis_client.xrange

        async def spying_xrange(
            name: str, min: str = "-", max: str = "+", count: int | None = None
        ) -> Any:
            result = await original_xrange(name, min, max, count)
            if name == dlq:
                batch_sizes.append(len(result))
            return result

        monkeypatch.setattr(redis_client, "xrange", spying_xrange)

        assert await consumer._already_retained_in_dlq(redis_client, msg_id) is True
        assert batch_sizes == [5, 5, 3]
    finally:
        await consumer._shutdown_executor()


@pytest.mark.asyncio
async def test_heartbeat_protects_in_flight_batch_and_releases_failed_sibling(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dans un lot mixte, une entrée lente reste protégée par le battement sans
    duplication, tandis qu'une entrée voisine restée en PEL (échec DLQ initial)
    sort immédiatement de _in_flight_ids et devient récupérable sans attendre la lente."""
    group = f"group-mixed-batch-{uuid4()}"

    async def get_connection() -> Redis:
        return redis_client

    from document_ia_infra.redis import redis_manager as redis_manager_module

    monkeypatch.setattr(
        redis_manager_module.redis_manager, "get_connection", get_connection
    )

    dlq_failures = 1
    original_xadd = redis_client.xadd

    async def fail_first_dlq_write(
        stream_name: str, fields: dict[str, Any], *args: Any, **kwargs: Any
    ) -> Any:
        nonlocal dlq_failures
        if stream_name == f"{stream}:dlq" and dlq_failures > 0:
            dlq_failures -= 1
            raise ConnectionError("temporary DLQ outage")
        return await original_xadd(stream_name, fields, *args, **kwargs)

    monkeypatch.setattr(redis_client, "xadd", fail_first_dlq_write)

    calls: list[str] = []
    slow_done = asyncio.Event()

    async def handler(
        message: SampleMessage, _retry_count: int, _is_last: bool
    ) -> None:
        kind = message.payload["kind"]
        calls.append(kind)
        if kind == "fail-pending":
            raise ValueError("fatal error")
        await asyncio.sleep(1.6)
        slow_done.set()

    consumer = AsyncIoConsumer[SampleMessage](
        consumer_name=build_instance_consumer_name("test-mixed"),
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=handler,
        max_retry_number=3,
        max_concurrency=4,
        reclaim_idle_ms=300,
    )

    fail_id = await redis_client.xadd(
        stream, {"data": json.dumps({"kind": "fail-pending"}), "retries": "0"}
    )
    await redis_client.xadd(
        stream, {"data": json.dumps({"kind": "slow-healthy"}), "retries": "0"}
    )

    await consumer.start()
    try:
        await asyncio.wait_for(slow_done.wait(), timeout=6)
        await wait_until(
            lambda: _pending_zero(redis_client, stream, group),
            timeout=6,
        )
        # L'entrée saine lente n'a été exécutée qu'une seule fois (protégée par XCLAIM JUSTID)
        assert calls.count("slow-healthy") == 1
        # L'entrée en échec a fini par être récupérée par le reclaimer et remise en file
        # (puis retraitée et envoyée en DLQ quand la DLQ est redevenue disponible)
        dlq_entries = await redis_client.xrange(f"{stream}:dlq")
        assert len(dlq_entries) == 1
        assert dlq_entries[0][1]["reason"] == "not_retryable_error"
        assert fail_id not in consumer._in_flight_ids
    finally:
        await consumer.stop()


async def _pending_zero(redis: Redis, stream: str, group: str) -> bool:
    return (await pending_count(redis, stream, group)) == 0


@pytest.mark.asyncio
async def test_reclaimed_work_is_heartbeat_protected_on_real_redis(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les entrées réclamées par XAUTOCLAIM sont protégées par le battement
    pendant toute la durée de _reclaim_entry."""
    group = f"group-reclaim-hb-{uuid4()}"
    consumer_name = build_instance_consumer_name("test-reclaim-hb")

    async def get_connection() -> Redis:
        return redis_client

    from document_ia_infra.redis import redis_manager as redis_manager_module

    monkeypatch.setattr(
        redis_manager_module.redis_manager, "get_connection", get_connection
    )

    delivered: list[str] = []
    handler_done = asyncio.Event()

    async def handler(
        message: SampleMessage, _retry_count: int, _is_last: bool
    ) -> None:
        delivered.append(message.payload["v"])
        handler_done.set()

    consumer = AsyncIoConsumer[SampleMessage](
        consumer_name=consumer_name,
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=handler,
        max_retry_number=3,
        max_concurrency=2,
        reclaim_idle_ms=300,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)
    await redis_client.xadd(
        stream, {"data": json.dumps({"v": "protected"}), "retries": "0"}
    )
    await redis_client.xreadgroup(group, "dead-consumer", {stream: ">"}, count=1)

    original_reclaim_entry = consumer._reclaim_entry

    async def delayed_reclaim_entry(
        conn: Redis, mid: str, fields: dict[str, Any] | None
    ) -> None:
        await asyncio.sleep(1.0)
        await original_reclaim_entry(conn, mid, fields)

    monkeypatch.setattr(consumer, "_reclaim_entry", delayed_reclaim_entry)

    await consumer.start()
    try:
        saw_claimed = False
        deadline = monotonic() + 8.0
        while monotonic() < deadline:
            pending_entries = await redis_client.xpending_range(
                stream, group, "-", "+", 10
            )
            claimed = [e for e in pending_entries if e["consumer"] == consumer_name]
            for entry in claimed:
                saw_claimed = True
                assert entry["time_since_delivered"] < 300
            if not pending_entries and saw_claimed:
                break
            await asyncio.sleep(0.04)

        assert saw_claimed
        await asyncio.wait_for(handler_done.wait(), timeout=5)
        assert delivered == ["protected"]
    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_heartbeat_protects_late_batch_delivered_during_shutdown_read(
    redis_client: Redis, stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un lot livré par un XREADGROUP bloqué juste après l'appel à stop() reste
    protégé par le battement jusqu'à la fin de sa vidange."""
    group = f"group-late-shutdown-{uuid4()}"

    async def get_connection() -> Redis:
        return redis_client

    from document_ia_infra.redis import redis_manager as redis_manager_module

    monkeypatch.setattr(
        redis_manager_module.redis_manager, "get_connection", get_connection
    )

    calls: list[str] = []
    handler_started = asyncio.Event()

    async def handler_a(_msg: SampleMessage, _retry_count: int, _is_last: bool) -> None:
        calls.append("a")
        handler_started.set()
        await asyncio.sleep(1.5)

    async def handler_b(_msg: SampleMessage, _retry_count: int, _is_last: bool) -> None:
        calls.append("b")

    consumer_a = AsyncIoConsumer[SampleMessage](
        consumer_name=build_instance_consumer_name("drain-a"),
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=5000,
        message_class=SampleMessage,
        process_message_callable=handler_a,
        reclaim_idle_ms=300,
    )
    consumer_b = AsyncIoConsumer[SampleMessage](
        consumer_name=build_instance_consumer_name("drain-b"),
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=10,
        message_class=SampleMessage,
        process_message_callable=handler_b,
        reclaim_idle_ms=300,
    )

    await redis_client.xgroup_create(stream, group, id="0-0", mkstream=True)

    await consumer_a.start()
    try:
        await asyncio.sleep(0.1)
        stopping = asyncio.create_task(consumer_a.stop())
        await asyncio.sleep(0.1)
        assert consumer_a.heartbeat_task is not None
        assert not consumer_a.heartbeat_task.done()

        await redis_client.xadd(
            stream, {"data": json.dumps({"late": True}), "retries": "0"}
        )
        await asyncio.wait_for(handler_started.wait(), timeout=5)
        await consumer_b.start()
        try:
            await stopping
            assert calls == ["a"]
            assert await redis_client.xlen(stream) == 1
            assert await pending_count(redis_client, stream, group) == 0
        finally:
            await consumer_b.stop()
    finally:
        await consumer_a.stop()


@pytest.mark.asyncio
async def test_multihop_retries_preserve_root_id_and_original_timestamp_in_dlq(
    redis_client: Redis, stream: str
) -> None:
    """Après plusieurs remises en file successives (M0 -> M1 -> M2 -> DLQ),
    root_id et original_timestamp conservent la trace de l'entrée initiale M0,
    tandis que original_id référence la dernière entrée M2 pour l'idempotence."""
    group = f"group-multihop-{uuid4()}"

    class FixedRedisManager:
        async def get_connection(self) -> Redis:
            return redis_client

        async def close(self) -> None:
            return None

    attempts: list[int] = []

    async def always_retry(
        _msg: SampleMessage, retry_count: int, _is_last: bool
    ) -> None:
        attempts.append(retry_count)
        raise RetryableException(f"transient-{retry_count}")

    consumer = AsyncIoConsumer[SampleMessage](
        consumer_name=build_instance_consumer_name("multihop"),
        consumer_group=group,
        stream_name=stream,
        batch_size=10,
        block_time=20,
        message_class=SampleMessage,
        process_message_callable=always_retry,
        max_retry_number=3,
        max_concurrency=2,
        current_redis_manager=FixedRedisManager(),  # type: ignore[arg-type]
    )

    m0_id = await redis_client.xadd(
        stream,
        {
            "data": json.dumps({"job": "root"}),
            "retries": "0",
            "timestamp": "2026-01-01T00:00:00+00:00",
        },
    )

    await consumer.start()
    try:

        async def reached_dlq() -> bool:
            return (
                await redis_client.xlen(f"{stream}:dlq") == 1
                and await pending_count(redis_client, stream, group) == 0
            )

        await wait_until(reached_dlq, timeout=5.0)
    finally:
        await consumer.stop()

    assert attempts == [0, 1, 2]
    stream_entries = await redis_client.xrange(stream)
    assert len(stream_entries) == 3
    m2_id = stream_entries[-1][0]

    dlq_entries = await redis_client.xrange(f"{stream}:dlq")
    assert len(dlq_entries) == 1
    dlq_fields = dlq_entries[0][1]
    assert dlq_fields["root_id"] == m0_id
    assert dlq_fields["original_id"] == m2_id
    assert dlq_fields["original_timestamp"] == "2026-01-01T00:00:00+00:00"
    assert dlq_fields["reason"] == "max_retries_exceeded"
