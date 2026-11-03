"""Real Redis acceptance tests for retention, outages and controlled replay."""

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
import httpx
from pydantic import ValidationError
from redis.exceptions import ResponseError

from document_ia_infra.redis.admission import AdmissionUnavailableError, admit_execution
from document_ia_infra.redis.maintenance import maintain, replay
from document_ia_infra.redis.redis_settings import RedisSettings, redis_settings
from document_ia_infra.redis.stream_delivery import StreamDelivery
from document_ia_infra.redis.failure_classification import classify_failure
from document_ia_infra.redis.worker_error_policy import WorkerErrorPolicy

from . import test_admission

queues = test_admission.queues

pytestmark = pytest.mark.asyncio


@pytest.fixture
def retention(monkeypatch):
    monkeypatch.setattr(redis_settings, "STREAM_COMPLETED_RETENTION_SECONDS", 1)
    monkeypatch.setattr(redis_settings, "STREAM_DLQ_RETENTION_SECONDS", 1)
    monkeypatch.setattr(redis_settings, "STREAM_CLEANUP_BATCH_SIZE", 2)


async def add_old(redis, stream, count=4):
    seconds, _ = await redis.time()
    return [
        await redis.xadd(
            stream, {"data": "private-document"}, id=f"{seconds * 1000 - 5000 + i}-0"
        )
        for i in range(count)
    ]


async def test_cleanup_protects_pending_and_undelivered_for_every_group(
    queues, retention
):
    stream, group = (
        redis_settings.EVENT_STREAM_NAME,
        redis_settings.EVENT_CONSUMER_GROUP,
    )
    ids = await add_old(queues, stream)
    await queues.xreadgroup(group, "one", {stream: ">"}, count=3)
    await queues.xack(stream, group, ids[0], ids[2])
    await queues.xgroup_create(stream, "other", id="0")
    # A second group has not even received the first message.
    assert (await maintain(queues, stream, apply=True))["completed_eligible"] == 0
    await queues.xreadgroup("other", "two", {stream: ">"}, count=4)
    await queues.xack(stream, "other", *ids)
    assert (await maintain(queues, stream))["completed_eligible"] == 1
    assert await queues.xlen(stream) == 4  # dry run is read-only
    await maintain(queues, stream, apply=True)
    assert [id for id, _ in await queues.xrange(stream)] == ids[1:]
    assert (await queues.xpending(stream, group))["pending"] == 1
    await queues.xack(stream, group, ids[1])
    await maintain(queues, stream, apply=True)
    assert [id for id, _ in await queues.xrange(stream)] == ids[2:]
    groups = {g["name"]: g for g in await queues.xinfo_groups(stream)}
    assert groups[group]["lag"] == 1


async def test_no_group_or_unknown_lag_never_deletes(queues, retention):
    stream, group = (
        redis_settings.EVENT_STREAM_NAME,
        redis_settings.EVENT_CONSUMER_GROUP,
    )
    ids = await add_old(queues, stream)
    await queues.xgroup_destroy(stream, group)
    result = await maintain(queues, stream, apply=True)
    assert result["lag"] == 4 and result["oldest_outstanding_ms"] >= 5000
    assert await queues.xlen(stream) == 4
    await queues.xgroup_create(
        stream, group, id=f"{ids[0].split('-')[0]}-1", entries_read=-1
    )
    assert (await queues.xinfo_groups(stream))[0]["lag"] is None
    with pytest.raises(ResponseError, match="lag unavailable"):
        await maintain(queues, stream, apply=True)
    assert await queues.xlen(stream) == 4


async def test_cleanup_bounded_and_keeps_recent_history(queues, retention):
    stream, group = (
        redis_settings.EVENT_STREAM_NAME,
        redis_settings.EVENT_CONSUMER_GROUP,
    )
    ids = await add_old(queues, stream, count=8)
    recent = await queues.xadd(stream, {"data": "recent"})
    await queues.xreadgroup(group, "worker", {stream: ">"}, count=9)
    await queues.xack(stream, group, *ids, recent)
    for expected in (7, 5, 3, 1):
        result = await maintain(queues, stream, apply=True)
        assert result["completed_eligible"] == 2
        assert result["retained"] == expected
    assert await queues.xrange(stream) == [(recent, {"data": "recent"})]


async def test_expired_dlq_copy_survives_failed_source_ack(queues, retention):
    stream, group = (
        redis_settings.EVENT_STREAM_NAME,
        redis_settings.EVENT_CONSUMER_GROUP,
    )
    ids = await add_old(queues, stream, count=2)
    await queues.xreadgroup(group, "worker", {stream: ">"}, count=2)
    dlq = f"{stream}:dlq"
    seconds, _ = await queues.time()
    failure = await queues.xadd(
        dlq, {"data": "private", "original_id": ids[0]}, id=f"{seconds * 1000 - 4000}-0"
    )
    await maintain(queues, stream, apply=True)
    assert await queues.xlen(dlq) == 1
    # Idempotence evidence must remain available after a lost ACK response.
    delivery = StreamDelivery(stream, group, "worker")
    assert await delivery.retain(queues, ids[0], {"data": "private"})
    assert await queues.xlen(dlq) == 1
    await queues.xack(stream, group, *ids)
    await maintain(queues, stream, apply=True)
    assert await queues.xrange(dlq, failure, failure) == []
    assert await queues.xlen(stream) == 1


async def test_pending_source_also_protects_completed_retry_copy(queues, retention):
    stream, group = (
        redis_settings.EVENT_STREAM_NAME,
        redis_settings.EVENT_CONSUMER_GROUP,
    )
    ids = await add_old(queues, stream, count=3)
    await queues.xreadgroup(group, "worker", {stream: ">"}, count=3)
    await queues.xack(stream, group, *ids[1:])
    assert (await maintain(queues, stream, apply=True))["completed_eligible"] == 0
    assert await queues.xlen(stream) == 3


async def test_old_unidentified_dlq_is_not_silently_deleted(queues, retention):
    stream = redis_settings.EVENT_STREAM_NAME
    await add_old(queues, f"{stream}:dlq")
    await maintain(queues, stream, apply=True)
    assert await queues.xlen(f"{stream}:dlq") == 4


@pytest.mark.parametrize("queue", ["EVENT_STREAM_NAME", "WEBHOOK_STREAM_NAME"])
async def test_retained_budget_closes_admission_until_low_watermark(
    queues, monkeypatch, queue
):
    monkeypatch.setattr(redis_settings, "ADMISSION_MAX_RETAINED", 4)
    monkeypatch.setattr(redis_settings, "ADMISSION_RESUME_RETAINED", 1)
    stream = getattr(redis_settings, queue)
    ids = [await queues.xadd(f"{stream}:dlq", {"data": "failure"}) for _ in range(4)]
    with pytest.raises(AdmissionUnavailableError):
        await admit_execution(queues)
    await queues.xdel(f"{stream}:dlq", ids[0])
    with pytest.raises(AdmissionUnavailableError):
        await admit_execution(queues)
    await queues.xdel(f"{stream}:dlq", *ids[1:3])
    await admit_execution(queues)


async def test_replay_requires_source_ack_and_checks_admission(queues, monkeypatch):
    stream, group = (
        redis_settings.EVENT_STREAM_NAME,
        redis_settings.EVENT_CONSUMER_GROUP,
    )
    source = await queues.xadd(stream, {"data": "private"})
    await queues.xreadgroup(group, "worker", {stream: ">"}, count=1)
    dlq = await queues.xadd(f"{stream}:dlq", {"data": "private", "original_id": source})
    with pytest.raises(ResponseError, match="not confirmed complete"):
        await replay(queues, stream, dlq)
    await queues.xack(stream, group, source)
    monkeypatch.setattr(redis_settings, "ADMISSION_MAX_RETAINED", 2)
    monkeypatch.setattr(redis_settings, "ADMISSION_RESUME_RETAINED", 1)
    with pytest.raises(ResponseError, match="Admission closed"):
        await replay(queues, stream, dlq)
    assert await queues.xlen(f"{stream}:dlq") == 1
    monkeypatch.setattr(redis_settings, "ADMISSION_MAX_RETAINED", 10)
    monkeypatch.setattr(redis_settings, "ADMISSION_RESUME_RETAINED", 8)
    new = await replay(queues, stream, dlq)
    assert await queues.xrange(stream, new, new) == [
        (new, {"data": "private", "retries": "0", "replayed_from": dlq})
    ]
    with pytest.raises(ResponseError, match="DLQ entry absent"):
        await replay(queues, stream, dlq)
    assert await queues.xlen(stream) == 2


async def test_concurrent_replay_is_once_and_rate_limited(queues):
    stream, group = (
        redis_settings.WEBHOOK_STREAM_NAME,
        redis_settings.WEBHOOK_CONSUMER_GROUP,
    )
    source = await queues.xadd(stream, {"data": "private"})
    await queues.xreadgroup(group, "worker", {stream: ">"}, count=1)
    await queues.xack(stream, group, source)
    dlqs = [
        await queues.xadd(f"{stream}:dlq", {"data": "private", "original_id": source})
        for _ in range(2)
    ]
    results = await asyncio.gather(
        *(replay(queues, stream, id) for id in [dlqs[0]] * 8), return_exceptions=True
    )
    assert sum(isinstance(r, str) for r in results) == 1
    with pytest.raises(ResponseError, match="rate limited"):
        await replay(queues, stream, dlqs[1])
    assert await queues.xlen(f"{stream}:dlq") == 1


async def test_recovery_read_limit_is_shared_across_instances(queues, monkeypatch):
    stream, group = (
        redis_settings.EVENT_STREAM_NAME,
        redis_settings.EVENT_CONSUMER_GROUP,
    )
    monkeypatch.setattr(redis_settings, "STREAM_RECOVERY_INTERVAL_MS", 60000)
    for _ in range(4):
        await queues.xadd(stream, {"data": "private"})
    workers = [StreamDelivery(stream, group, f"worker-{i}") for i in range(8)]
    results = await asyncio.gather(*(w.read(queues, 10, 1) for w in workers))
    assert sum(len(entries) for result in results for _, entries in result) == 1
    assert (await queues.xpending(stream, group))["pending"] == 1
    # A new interval permits exactly one more, without draining the whole backlog.
    await queues.delete(f"{stream}:recovery:read")
    assert len((await workers[1].read(queues, 10, 1))[0][1]) == 1


async def test_metrics_do_not_include_document_or_error_contents(queues, caplog):
    stream, group = (
        redis_settings.EVENT_STREAM_NAME,
        redis_settings.EVENT_CONSUMER_GROUP,
    )
    delivery = StreamDelivery(stream, group, "worker")
    with caplog.at_level(logging.INFO):
        await delivery.retain(
            queues, "1-0", {"data": "SECRET-DOCUMENT", "error": "SECRET-ERROR"}
        )
        await delivery.retain(queues, "1-0", {"data": "SECRET-DOCUMENT"})
        broken = AsyncMock()
        broken.eval.side_effect = RuntimeError("SECRET-ERROR")
        broken.xack.side_effect = RuntimeError("SECRET-ERROR")
        with pytest.raises(RuntimeError):
            await delivery.retain(broken, "2-0", {"data": "SECRET-DOCUMENT"})
        with pytest.raises(RuntimeError):
            await delivery.ack(broken, "2-0")
    assert "operation=dlq outcome=created value=1" in caplog.text
    assert "operation=dlq outcome=existing value=1" in caplog.text
    assert "operation=dlq outcome=error value=1" in caplog.text
    assert "operation=ack outcome=error value=1" in caplog.text
    assert "SECRET-" not in caplog.text


@pytest.mark.parametrize(
    "values",
    [
        {"ADMISSION_MAX_RETAINED": 4, "ADMISSION_RESUME_RETAINED": 4},
        {"STREAM_COMPLETED_RETENTION_SECONDS": 0},
        {"STREAM_DLQ_RETENTION_SECONDS": 0},
        {"STREAM_CLEANUP_BATCH_SIZE": 1001},
        {"STREAM_RECOVERY_INTERVAL_MS": -1},
    ],
)
async def test_invalid_retention_settings(values):
    with pytest.raises(ValidationError):
        RedisSettings(**values)


@pytest.mark.parametrize(
    "status,category",
    [
        (400, "permanent"),
        (401, "permanent"),
        (403, "permanent"),
        (404, "permanent"),
        (422, "permanent"),
        (408, "temporary"),
        (425, "temporary"),
        (429, "temporary"),
        (500, "temporary"),
        (503, "temporary"),
        (302, "internal"),
    ],
)
async def test_dependency_status_classification(status, category):
    error = httpx.HTTPStatusError(
        "private",
        request=httpx.Request("GET", "https://example.test"),
        response=httpx.Response(status),
    )
    assert classify_failure(error) == category
    future = asyncio.get_running_loop().create_future()
    future.set_exception(error)
    retain, requeue = AsyncMock(return_value=True), AsyncMock(return_value=True)
    delivery = AsyncMock(stream="work")
    await WorkerErrorPolicy(3).finish(
        future, "1-0", {"data": "private"}, AsyncMock(), delivery, requeue, retain
    )
    # The worker's explicit RetryableException contract is not broadened by
    # classification: WorkflowManager owns terminal state/webhook decisions.
    requeue.assert_not_awaited()
    retain.assert_awaited_once()
    assert retain.await_args.args[2]["failure_class"] == category
    delivery.ack.assert_awaited_once()


async def test_dependency_and_internal_error_classes():
    assert classify_failure(httpx.ReadTimeout("private")) == "temporary"
    assert classify_failure(ValueError("private")) == "permanent"
    assert classify_failure(RuntimeError("private")) == "internal"


async def test_prolonged_outage_retains_work_and_resumes_boundedly(
    queues, retention, monkeypatch
):
    stream, group = (
        redis_settings.EVENT_STREAM_NAME,
        redis_settings.EVENT_CONSUMER_GROUP,
    )
    seconds, _ = await queues.time()
    ids = [
        await queues.xadd(
            stream,
            {"data": "private", "retries": "0"},
            id=f"{seconds * 1000 - 120000 + i}-0",
        )
        for i in range(3)
    ]
    delivery = StreamDelivery(stream, group, "worker")
    await queues.xreadgroup(group, "dead-worker", {stream: ">"}, count=3)
    with pytest.raises(AdmissionUnavailableError):
        await admit_execution(queues)
    # Redis can read but cannot retain failures (wrong-type DLQ witnesses the failure).
    await queues.set(f"{stream}:dlq", "unavailable")
    with pytest.raises(ResponseError):
        await delivery.retain(queues, ids[0], {"data": "private"})
    assert (await queues.xpending(stream, group))["pending"] == 3
    await queues.delete(f"{stream}:dlq")
    await maintain(queues, stream, apply=True)
    assert await queues.xlen(stream) == 3
    monkeypatch.setattr(redis_settings, "STREAM_RECOVERY_INTERVAL_MS", 60000)
    claimed = await delivery.claim(queues, 0, "0-0", 100)
    assert len(claimed[1]) == 1
    assert (await delivery.claim(queues, 0, "0-0", 100))[1] == []
    entry, fields = claimed[1][0]
    await delivery.requeue(queues, entry, fields, 1)
    await delivery.ack(queues, entry)
    # Outstanding old work still closes admission; recovery must not override it.
    with pytest.raises(AdmissionUnavailableError):
        await admit_execution(queues)
    assert await queues.xlen(stream) == 4
    assert await queues.xrange(stream, ids[1], ids[2])
    # Drain accepted work, including the retry copy, then reopen at low watermarks.
    await queues.xreadgroup(group, "recovered", {stream: ">"}, count=10)
    all_ids = [entry for entry, _ in await queues.xrange(stream)]
    await queues.xack(stream, group, *all_ids)
    await admit_execution(queues)
