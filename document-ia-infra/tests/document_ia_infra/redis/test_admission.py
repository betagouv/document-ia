"""Admission tests use real Redis, including concurrent independent publishers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError
from redis.asyncio import Redis
from redis.exceptions import AuthenticationError

from document_ia_infra.redis.admission import AdmissionUnavailableError, admit_execution
from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)
from document_ia_infra.redis.publisher import PublishFailedError, Publisher
from document_ia_infra.redis.redis_manager import RedisManager
from document_ia_infra.redis.redis_settings import RedisSettings, redis_settings

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def queues(monkeypatch):
    prefix = f"admission-test:{uuid4()}"
    monkeypatch.setattr(redis_settings, "EVENT_STREAM_NAME", f"{prefix}:work")
    monkeypatch.setattr(redis_settings, "WEBHOOK_STREAM_NAME", f"{prefix}:hooks")
    monkeypatch.setattr(redis_settings, "ADMISSION_MAX_OUTSTANDING", 4)
    monkeypatch.setattr(redis_settings, "ADMISSION_RESUME_OUTSTANDING", 1)
    monkeypatch.setattr(redis_settings, "ADMISSION_MAX_AGE_SECONDS", 60)
    monkeypatch.setattr(redis_settings, "ADMISSION_RESUME_AGE_SECONDS", 10)
    connection = Redis(
        host=redis_settings.REDIS_HOST,
        port=redis_settings.REDIS_PORT,
        db=redis_settings.REDIS_DB,
        password=redis_settings.REDIS_PASSWORD.get_secret_value(),
        decode_responses=True,
    )
    # Deliberately fail, not skip: these regressions require the CI Redis service.
    try:
        await connection.ping()
    except AuthenticationError as exc:
        # CI currently starts an unauthenticated Redis despite REDIS_PASSWORD.
        if "without any password configured" not in str(exc):
            raise
        await connection.aclose()
        connection = Redis(
            host=redis_settings.REDIS_HOST,
            port=redis_settings.REDIS_PORT,
            db=redis_settings.REDIS_DB,
            decode_responses=True,
        )
        await connection.ping()
    for stream, group in (
        (redis_settings.EVENT_STREAM_NAME, redis_settings.EVENT_CONSUMER_GROUP),
        (redis_settings.WEBHOOK_STREAM_NAME, redis_settings.WEBHOOK_CONSUMER_GROUP),
    ):
        await connection.xgroup_create(stream, group, id="0", mkstream=True)
    yield connection
    keys = await connection.keys(f"{prefix}:*")
    if keys:
        await connection.delete(*keys)
    await connection.aclose()


def publisher(connection):
    return Publisher(
        redis_settings.EVENT_STREAM_NAME,
        SimpleNamespace(get_connection=AsyncMock(return_value=connection)),
    )


async def publish(connection):
    return await publisher(connection).publish_message(
        WorkflowExecutionMessage(workflow_execution_id=str(uuid4()))
    )


async def test_concurrent_instances_cannot_overbook(queues):
    results = await asyncio.gather(
        *(publish(queues) for _ in range(40)), return_exceptions=True
    )
    assert sum(isinstance(result, str) for result in results) == 4
    assert sum(isinstance(result, PublishFailedError) for result in results) == 36
    assert await queues.xlen(redis_settings.EVENT_STREAM_NAME) == 4


async def test_pending_and_waiting_count_and_reopen_only_below_low_watermark(queues):
    stream = redis_settings.EVENT_STREAM_NAME
    group = redis_settings.EVENT_CONSUMER_GROUP
    ids = [await publish(queues) for _ in range(4)]
    await queues.xreadgroup(group, "worker", {stream: ">"}, count=2)
    with pytest.raises(PublishFailedError):
        await publish(queues)
    await queues.xack(stream, group, ids[0])
    with pytest.raises(PublishFailedError):
        await publish(queues)
    await queues.xreadgroup(group, "worker", {stream: ">"}, count=2)
    await queues.xack(stream, group, *ids[1:3])
    assert await publish(queues)
    # ACKed history is not outstanding work, and has not been trimmed away.
    assert await queues.xlen(stream) == 5


@pytest.mark.parametrize("queue", ["work", "hooks"])
@pytest.mark.parametrize("pending", [False, True])
async def test_oldest_outstanding_closes_admission(queues, queue, pending):
    stream = (
        redis_settings.EVENT_STREAM_NAME
        if queue == "work"
        else redis_settings.WEBHOOK_STREAM_NAME
    )
    group = (
        redis_settings.EVENT_CONSUMER_GROUP
        if queue == "work"
        else redis_settings.WEBHOOK_CONSUMER_GROUP
    )
    seconds, micros = await queues.time()
    old_ms = seconds * 1000 + micros // 1000 - 61000
    old_id = await queues.xadd(stream, {"data": "old"}, id=f"{old_ms}-0")
    if pending:
        await queues.xreadgroup(group, "stuck", {stream: ">"}, count=1)
    with pytest.raises(AdmissionUnavailableError):
        await admit_execution(queues)
    assert await queues.xlen(redis_settings.EVENT_STREAM_NAME) == (queue == "work")
    if not pending:
        await queues.xreadgroup(group, "recovered", {stream: ">"}, count=1)
    await queues.xack(stream, group, old_id)
    assert await publish(queues)


async def test_age_hysteresis_does_not_reopen_at_intermediate_age(queues):
    stream = redis_settings.EVENT_STREAM_NAME
    group = redis_settings.EVENT_CONSUMER_GROUP
    seconds, _ = await queues.time()
    old = await queues.xadd(stream, {"data": "old"}, id=f"{seconds * 1000 - 61000}-0")
    middle = await queues.xadd(
        stream, {"data": "middle"}, id=f"{seconds * 1000 - 30000}-0"
    )
    with pytest.raises(AdmissionUnavailableError):
        await admit_execution(queues)
    await queues.xreadgroup(group, "worker", {stream: ">"}, count=2)
    await queues.xack(stream, group, old)
    with pytest.raises(AdmissionUnavailableError):
        await admit_execution(queues)
    await queues.xack(stream, group, middle)
    assert await publish(queues)


async def test_webhook_outage_blocks_new_work_but_not_delivery_publication(queues):
    stream = redis_settings.WEBHOOK_STREAM_NAME
    for _ in range(4):
        await queues.xadd(stream, {"data": "webhook"})
    with pytest.raises(PublishFailedError):
        await publish(queues)
    delivery_publisher = Publisher(
        stream, SimpleNamespace(get_connection=AsyncMock(return_value=queues))
    )
    # Completing already accepted work must not deadlock behind new-work admission.
    await delivery_publisher.publish_message(
        WorkflowExecutionMessage(workflow_execution_id="existing")
    )
    assert await queues.xlen(stream) == 5


async def test_group_not_created_yet_counts_all_entries(queues):
    await queues.xgroup_destroy(
        redis_settings.EVENT_STREAM_NAME, redis_settings.EVENT_CONSUMER_GROUP
    )
    for _ in range(4):
        await publish(queues)
    with pytest.raises(PublishFailedError):
        await publish(queues)


async def test_unknown_group_lag_refuses_publication(queues):
    stream = redis_settings.EVENT_STREAM_NAME
    group = redis_settings.EVENT_CONSUMER_GROUP
    seconds, _ = await queues.time()
    base = seconds * 1000
    for offset in (0, 2, 4):
        await queues.xadd(stream, {"data": "entry"}, id=f"{base + offset}-0")
    await queues.xgroup_setid(stream, group, f"{base + 1}-0", entries_read=-1)
    assert (await queues.xinfo_groups(stream))[0]["lag"] is None
    with pytest.raises(PublishFailedError):
        await publish(queues)
    assert await queues.xlen(stream) == 3


async def test_preflight_does_not_reserve_and_final_publish_rechecks(queues):
    for _ in range(8):
        await admit_execution(queues)
    assert await queues.xlen(redis_settings.EVENT_STREAM_NAME) == 0
    for _ in range(4):
        await publish(queues)
    with pytest.raises(PublishFailedError):
        await publish(queues)


async def test_no_maxlen_drops_unfinished_work(queues, monkeypatch):
    monkeypatch.setattr(redis_settings, "EVENT_STREAM_MAXLEN", 1)
    first = await publish(queues)
    await publish(queues)
    assert (await queues.xrange(redis_settings.EVENT_STREAM_NAME))[0][0] == first


async def test_shared_manager_allows_idle_worker_block_longer_than_five_seconds(
    queues, monkeypatch
):
    options = queues.connection_pool.connection_kwargs
    monkeypatch.setattr(redis_settings, "REDIS_URL", None)
    monkeypatch.setattr(
        redis_settings, "REDIS_PASSWORD", SecretStr(options.get("password") or "")
    )
    manager = RedisManager()
    try:
        connection = await manager.get_connection()
        assert connection is not None
        # The worker uses BLOCK 10000. A shared socket_timeout=5 must fail here.
        assert (
            await connection.xreadgroup(
                redis_settings.EVENT_CONSUMER_GROUP,
                "idle-worker",
                {redis_settings.EVENT_STREAM_NAME: ">"},
                block=10000,
                count=1,
            )
            == []
        )
    finally:
        await manager.close()


@pytest.mark.parametrize(
    "values",
    [
        {"ADMISSION_MAX_OUTSTANDING": 4, "ADMISSION_RESUME_OUTSTANDING": 4},
        {"ADMISSION_MAX_AGE_SECONDS": 10, "ADMISSION_RESUME_AGE_SECONDS": 10},
        {"EVENT_STREAM_NAME": "same", "WEBHOOK_STREAM_NAME": "same"},
    ],
)
async def test_invalid_thresholds_rejected(values):
    with pytest.raises(ValidationError):
        RedisSettings(**values)
