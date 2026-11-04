"""Integration tests for the unified webhook Consumer and WebhookNotificationService."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.exc import OperationalError

from document_ia_api.infra.webhook_notification_service import (
    WebhookNotificationService,
)
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.webhook.dto.webhook_dto import WebHookDTO
from document_ia_infra.redis.consumer import (
    AsyncIoConsumer,
    build_instance_consumer_name,
)
from document_ia_infra.redis.model.webhook_message import WebHookMessage
from document_ia_infra.redis.serializable_message import SerializableMessage


@dataclass
class SampleWebhookMessage(SerializableMessage):
    workflow_execution_id: str
    webhook_url: str

    def to_dict(self) -> dict[str, str]:
        return {
            "workflow_execution_id": self.workflow_execution_id,
            "webhook_url": self.webhook_url,
        }

    @staticmethod
    def from_json(data: str) -> SampleWebhookMessage:
        payload = json.loads(data)
        return SampleWebhookMessage(
            workflow_execution_id=payload["workflow_execution_id"],
            webhook_url=payload["webhook_url"],
        )


def _make_webhook_dto(webhook_id: UUID, url: str) -> WebHookDTO:
    now = datetime.now(UTC)
    return WebHookDTO(
        id=webhook_id,
        organization_id=uuid4(),
        url=url,
        headers={"X-Webhook-Test": "1"},
        created_at=now,
        updated_at=now,
    )


def _make_event_dto(execution_id: str) -> EventDTO:
    org_id = uuid4()
    return EventDTO(
        id=uuid4(),
        workflow_id="wf-webhook-test",
        organization_id=org_id,
        execution_id=execution_id,
        created_at=datetime.now(UTC),
        event_type=EventType.WORKFLOW_EXECUTION_STARTED,
        event={
            "workflow_id": "wf-webhook-test",
            "execution_id": execution_id,
            "organization_id": str(org_id),
            "created_at": datetime.now(UTC).isoformat(),
            "version": 1,
            "s3_file_info": None,
            "file_url": "https://example.test/doc.pdf",
            "metadata": {},
            "classification_parameters": {},
            "extraction_parameters": {},
        },
    )


def _make_api_consumer(
    *,
    stream_name: str,
    consumer_group: str,
    message_class: type[Any],
    handler: Callable[[Any, int, bool], Any],
    max_retry_number: int = 4,
    block_time: int = 20,
    reclaim_idle_ms: int = 5000,
) -> AsyncIoConsumer[Any]:
    return AsyncIoConsumer(
        consumer_name=build_instance_consumer_name("api-webhook-test"),
        consumer_group=consumer_group,
        stream_name=stream_name,
        batch_size=50,
        block_time=block_time,
        message_class=message_class,
        process_message_callable=handler,
        max_retry_number=max_retry_number,
        max_concurrency=10,
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


async def _dlq_len(redis: Redis, stream: str) -> int:
    return await redis.xlen(f"{stream}:dlq")


async def _pending_count(redis: Redis, stream: str, group: str) -> int:
    info = await redis.xpending(stream, group)
    return info["pending"] if isinstance(info, dict) else info.pending


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


async def _append_message(
    redis: Redis, stream: str, message: SerializableMessage
) -> str:
    return await redis.xadd(stream, {"data": json.dumps(message.to_dict())})


def _mockserver_webhook_handler(
    service: WebhookNotificationService,
) -> Callable[[SampleWebhookMessage, int, bool], Awaitable[None]]:
    webhook_id = uuid4()

    async def _handler(
        message: SampleWebhookMessage, retry_count: int, is_last_retry: bool
    ) -> None:
        webhook_dto = _make_webhook_dto(webhook_id, message.webhook_url)
        event_dto = _make_event_dto(message.workflow_execution_id)
        await service._deliver_webhook_with_retry_policy(
            webhook_dto,
            event_dto,
            retry_count=retry_count,
            is_last_retry=is_last_retry,
        )

    return _handler


@pytest.fixture(autouse=True)
def mock_api_key_service_auth() -> None:
    """Consumer integration tests do not exercise API authentication."""


@pytest.fixture(autouse=True)
def use_test_redis(monkeypatch: pytest.MonkeyPatch, redis_client: Redis) -> None:
    from document_ia_infra.redis import redis_manager as redis_manager_module

    async def get_connection() -> Redis:
        return redis_client

    monkeypatch.setattr(
        redis_manager_module.redis_manager, "get_connection", get_connection
    )


@pytest.fixture
async def redis_client():
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


@pytest.fixture(scope="session")
def mockserver_base_url() -> str:
    url = "http://localhost:1080"
    try:
        response = httpx.get(f"{url}/status", timeout=1.0)
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - infra dependency
        pytest.skip(f"MockServer not available at {url}: {exc}")
    return url


@pytest.mark.asyncio
async def test_consumer_acknowledges_success(
    redis_client: Redis,
    mockserver_base_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = f"test_webhook_stream_ok:{uuid4()}"
    group = f"group-ok-{uuid4()}"
    handler_called = asyncio.Event()
    service = WebhookNotificationService(retry_initial_delay_seconds=0.1)
    base_handler = _mockserver_webhook_handler(service)

    async def record_handler(
        message: SampleWebhookMessage, retry_count: int, is_last_retry: bool
    ) -> None:
        await base_handler(message, retry_count, is_last_retry)
        handler_called.set()

    consumer = _make_api_consumer(
        stream_name=stream,
        consumer_group=group,
        message_class=SampleWebhookMessage,
        handler=record_handler,
    )

    message = SampleWebhookMessage(
        workflow_execution_id=str(uuid4()),
        webhook_url=f"{mockserver_base_url}/webhook/ok",
    )
    await _append_message(redis_client, stream, message)

    original_xack = redis_client.xack
    acknowledged = asyncio.Event()

    async def record_ack(stream_name: str, group_name: str, entry_id: str) -> int:
        result = await original_xack(stream_name, group_name, entry_id)
        acknowledged.set()
        return result

    monkeypatch.setattr(redis_client, "xack", record_ack)
    await consumer.start()
    try:
        await asyncio.wait_for(handler_called.wait(), timeout=3)
        await asyncio.wait_for(acknowledged.wait(), timeout=3)
        assert await _pending_count(redis_client, stream, group) == 0
        assert await _dlq_len(redis_client, stream) == 0
    finally:
        await consumer.stop()
        await service.aclose()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
@pytest.mark.parametrize("error_class", [httpx.ReadTimeout, httpx.ConnectError])
async def test_consumer_requeues_http_transport_failure_then_dlqs_when_exhausted(
    redis_client: Redis,
    error_class: type[httpx.TransportError],
) -> None:
    """Une erreur réseau httpx (ReadTimeout, ConnectError) est convertie en
    RetryableException : remise en file jusqu'à épuisement puis DLQ."""
    stream = f"test_webhook_transport:{uuid4()}"
    group = f"group-transport-{uuid4()}"
    attempts_seen: list[tuple[int, bool]] = []
    service = WebhookNotificationService(retry_initial_delay_seconds=0.05)

    async def fail_transport(
        message: SampleWebhookMessage, retry_count: int, is_last_retry: bool
    ) -> None:
        attempts_seen.append((retry_count, is_last_retry))
        webhook_dto = _make_webhook_dto(uuid4(), message.webhook_url)
        event_dto = _make_event_dto(message.workflow_execution_id)

        async def _raise_transport(_wh: WebHookDTO, _ev: EventDTO) -> None:
            request = httpx.Request("POST", message.webhook_url)
            raise error_class("webhook transport failed", request=request)

        service._call_webhook_notification = _raise_transport  # type: ignore[method-assign]
        await service._deliver_webhook_with_retry_policy(
            webhook_dto,
            event_dto,
            retry_count=retry_count,
            is_last_retry=is_last_retry,
        )

    consumer = _make_api_consumer(
        stream_name=stream,
        consumer_group=group,
        message_class=SampleWebhookMessage,
        handler=fail_transport,
        max_retry_number=2,
    )
    message = SampleWebhookMessage(
        workflow_execution_id=str(uuid4()),
        webhook_url="http://localhost:1080/webhook",
    )
    await _append_message(redis_client, stream, message)

    await consumer.start()
    try:
        await _wait_until(_dlq_len_is_pred(redis_client, stream, 1), timeout=5)
        await _wait_until(_pending_is_zero_pred(redis_client, stream, group), timeout=5)
        assert attempts_seen == [(0, False), (1, True)]
        dlq_entries = await redis_client.xrange(f"{stream}:dlq")
        assert len(dlq_entries) == 1
        assert dlq_entries[0][1]["reason"] == "max_retries_exceeded"
        assert dlq_entries[0][1]["retries"] == "1"
    finally:
        await consumer.stop()
        await service.aclose()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_consumer_requeues_transient_database_failure_and_recovers(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une panne transitoire PostgreSQL (OperationalError) déclenche une remise
    en file via RetryableException et aboutit lorsque la base redevient joignable."""
    from document_ia_api.infra import webhook_notification_service as svc_mod

    stream = f"test_webhook_database:{uuid4()}"
    group = f"group-database-{uuid4()}"
    webhook_id = uuid4()
    execution_id = str(uuid4())
    webhook_dto = _make_webhook_dto(webhook_id, "https://example.test/hook")
    event_dto = _make_event_dto(execution_id)

    db_calls = 0
    delivered = asyncio.Event()

    @asynccontextmanager
    async def flaky_session():
        nonlocal db_calls
        db_calls += 1
        if db_calls == 1:
            raise OperationalError(
                "connect", {}, ConnectionError("database unavailable")
            )
        yield object()

    class FakeWebhookRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, _wid: UUID) -> WebHookDTO:
            return webhook_dto

    class FakeEventRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_last_event_by_execution_id(self, _eid: str) -> EventDTO:
            return event_dto

    monkeypatch.setattr(svc_mod.database_manager, "local_session", flaky_session)
    monkeypatch.setattr(svc_mod, "WebHookRepository", FakeWebhookRepo)
    monkeypatch.setattr(svc_mod, "EventRepository", FakeEventRepo)

    service = WebhookNotificationService(retry_initial_delay_seconds=0.05)

    async def fake_http(_wh: WebHookDTO, _ev: EventDTO) -> None:
        delivered.set()

    monkeypatch.setattr(service, "_call_webhook_notification", fake_http)

    consumer = _make_api_consumer(
        stream_name=stream,
        consumer_group=group,
        message_class=WebHookMessage,
        handler=service.handle_webhook_notification,
        max_retry_number=3,
    )
    await _append_message(
        redis_client,
        stream,
        WebHookMessage(workflow_execution_id=execution_id, webhook_id=webhook_id),
    )

    await consumer.start()
    try:
        await asyncio.wait_for(delivered.wait(), timeout=5)
        await _wait_until(_pending_is_zero_pred(redis_client, stream, group), timeout=5)
        assert db_calls == 2
        assert await _dlq_len(redis_client, stream) == 0
        entries = await redis_client.xrange(stream)
        assert len(entries) == 2
        assert entries[1][1]["retries"] == "1"
    finally:
        await consumer.stop()
        await service.aclose()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
@pytest.mark.parametrize("dlq_available", [True, False])
async def test_consumer_invalid_json_requires_dlq_before_ack(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
    dlq_available: bool,
) -> None:
    """Un payload JSON illisible va immédiatement en DLQ (decode_error) avant
    XACK ; si la DLQ est indisponible, l'entrée reste en PEL."""
    stream = f"test_webhook_invalid_json:{uuid4()}"
    group = f"group-invalid-json-{uuid4()}"
    dlq_attempted = asyncio.Event()

    async def should_not_run(
        _message: SampleWebhookMessage, _rc: int, _last: bool
    ) -> None:
        pytest.fail("Invalid JSON must not reach the webhook handler")

    consumer = _make_api_consumer(
        stream_name=stream,
        consumer_group=group,
        message_class=SampleWebhookMessage,
        handler=should_not_run,
    )
    await redis_client.xadd(stream, {"data": "{invalid-json}"})

    original_xadd = redis_client.xadd
    original_eval = redis_client.eval

    async def record_dlq_attempt(
        stream_name: str, fields: dict[str, Any], *args: Any, **kwargs: Any
    ) -> Any:
        if stream_name == f"{stream}:dlq":
            dlq_attempted.set()
            if not dlq_available:
                raise ConnectionError("DLQ unavailable")
        return await original_xadd(stream_name, fields, *args, **kwargs)

    async def record_dlq_eval(script: str, numkeys: int, *args: Any) -> Any:
        if args and args[0] == f"{stream}:dlq":
            dlq_attempted.set()
            if not dlq_available:
                raise ConnectionError("DLQ unavailable")
        return await original_eval(script, numkeys, *args)

    monkeypatch.setattr(redis_client, "xadd", record_dlq_attempt)
    monkeypatch.setattr(redis_client, "eval", record_dlq_eval)

    await consumer.start()
    try:
        await asyncio.wait_for(dlq_attempted.wait(), timeout=3)

        async def expected_state() -> bool:
            pending = await _pending_count(redis_client, stream, group)
            dlq_length = await _dlq_len(redis_client, stream)
            if dlq_available:
                return pending == 0 and dlq_length == 1
            return pending == 1 and dlq_length == 0

        await _wait_until(expected_state, timeout=5)
        if dlq_available:
            dlq_entries = await redis_client.xrange(f"{stream}:dlq")
            assert dlq_entries[0][1]["reason"] == "decode_error"
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
@pytest.mark.parametrize("dlq_available", [True, False])
async def test_consumer_terminal_http_error_requires_dlq_before_ack(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
    dlq_available: bool,
) -> None:
    stream = f"test_webhook_terminal:{uuid4()}"
    group = f"group-terminal-{uuid4()}"
    dlq_attempted = asyncio.Event()
    service = WebhookNotificationService(retry_initial_delay_seconds=5.0)

    async def reject_webhook(
        message: SampleWebhookMessage, retry_count: int, is_last_retry: bool
    ) -> None:
        webhook_dto = _make_webhook_dto(uuid4(), message.webhook_url)
        event_dto = _make_event_dto(message.workflow_execution_id)

        async def _raise_400(_wh: WebHookDTO, _ev: EventDTO) -> None:
            request = httpx.Request("POST", message.webhook_url)
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError(
                "bad request", request=request, response=response
            )

        service._call_webhook_notification = _raise_400  # type: ignore[method-assign]
        await service._deliver_webhook_with_retry_policy(
            webhook_dto,
            event_dto,
            retry_count=retry_count,
            is_last_retry=is_last_retry,
        )

    consumer = _make_api_consumer(
        stream_name=stream,
        consumer_group=group,
        message_class=SampleWebhookMessage,
        handler=reject_webhook,
    )
    original_xadd = redis_client.xadd
    original_eval = redis_client.eval
    operations: list[str] = []

    async def record_dlq_attempt(
        stream_name: str, fields: dict[str, Any], *args: Any, **kwargs: Any
    ) -> Any:
        operations.append(f"xadd:{stream_name}")
        if stream_name == f"{stream}:dlq":
            dlq_attempted.set()
            if not dlq_available:
                raise ConnectionError("DLQ unavailable")
        return await original_xadd(stream_name, fields, *args, **kwargs)

    async def record_dlq_eval(script: str, numkeys: int, *args: Any) -> Any:
        stream_name = args[0] if args else ""
        operations.append(f"xadd:{stream_name}")
        if stream_name == f"{stream}:dlq":
            dlq_attempted.set()
            if not dlq_available:
                raise ConnectionError("DLQ unavailable")
        return await original_eval(script, numkeys, *args)

    message = SampleWebhookMessage(
        workflow_execution_id=str(uuid4()),
        webhook_url="http://localhost:1080/webhook",
    )
    await _append_message(redis_client, stream, message)
    monkeypatch.setattr(redis_client, "xadd", record_dlq_attempt)
    monkeypatch.setattr(redis_client, "eval", record_dlq_eval)

    original_xack = redis_client.xack

    async def record_ack(stream_name: str, group_name: str, entry_id: str) -> int:
        operations.append(f"xack:{stream_name}")
        return await original_xack(stream_name, group_name, entry_id)

    monkeypatch.setattr(redis_client, "xack", record_ack)

    await consumer.start()
    try:
        await asyncio.wait_for(dlq_attempted.wait(), timeout=3)

        async def reached_expected_state() -> bool:
            pending = await _pending_count(redis_client, stream, group)
            dlq_length = await _dlq_len(redis_client, stream)
            if dlq_available:
                return pending == 0 and dlq_length == 1
            return pending == 1 and dlq_length == 0

        await _wait_until(reached_expected_state, timeout=5)
        if dlq_available:
            assert operations == [f"xadd:{stream}:dlq", f"xack:{stream}"]
            dlq_entries = await redis_client.xrange(f"{stream}:dlq")
            assert dlq_entries[0][1]["reason"] == "not_retryable_error"
        else:
            assert operations == [f"xadd:{stream}:dlq"]
    finally:
        await consumer.stop()
        await service.aclose()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_consumer_retries_then_dlq_on_429(
    redis_client: Redis, mockserver_base_url: str
) -> None:
    stream = f"test_webhook_stream_ko:{uuid4()}"
    group = f"group-ko-{uuid4()}"
    service = WebhookNotificationService(
        retry_initial_delay_seconds=1.0,
        retry_backoff_multiplier=1.0,
    )
    consumer = _make_api_consumer(
        stream_name=stream,
        consumer_group=group,
        message_class=SampleWebhookMessage,
        handler=_mockserver_webhook_handler(service),
        max_retry_number=2,
    )

    message = SampleWebhookMessage(
        workflow_execution_id=str(uuid4()),
        webhook_url=f"{mockserver_base_url}/webhook/ko",
    )
    await _append_message(redis_client, stream, message)

    start = monotonic()
    await consumer.start()
    try:
        await _wait_until(
            _dlq_len_is_pred(redis_client, stream, expected=1), timeout=10
        )
        elapsed = monotonic() - start
        assert elapsed >= 1.0, "Expected at least one retry delay before DLQ"
        await _wait_until(_pending_is_zero_pred(redis_client, stream, group))
        dlq_entries = await redis_client.xrange(f"{stream}:dlq")
        assert dlq_entries[0][1]["reason"] == "max_retries_exceeded"
    finally:
        await consumer.stop()
        await service.aclose()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_consumer_immediate_dlq_on_401(
    redis_client: Redis, mockserver_base_url: str
) -> None:
    stream = f"test_webhook_stream_unauthorized:{uuid4()}"
    group = f"group-unauth-{uuid4()}"
    service = WebhookNotificationService(
        retry_initial_delay_seconds=5.0,
        retry_backoff_multiplier=2.0,
    )
    consumer = _make_api_consumer(
        stream_name=stream,
        consumer_group=group,
        message_class=SampleWebhookMessage,
        handler=_mockserver_webhook_handler(service),
        max_retry_number=4,
    )

    message = SampleWebhookMessage(
        workflow_execution_id=str(uuid4()),
        webhook_url=f"{mockserver_base_url}/webhook/kko",
    )
    await _append_message(redis_client, stream, message)

    start = monotonic()
    await consumer.start()
    try:
        await _wait_until(_dlq_len_is_pred(redis_client, stream, expected=1))
        elapsed = monotonic() - start
        assert elapsed < 3.0, "401 must go immediately to DLQ without retry backoff"
        await _wait_until(_pending_is_zero_pred(redis_client, stream, group))
        dlq_entries = await redis_client.xrange(f"{stream}:dlq")
        assert dlq_entries[0][1]["reason"] == "not_retryable_error"
    finally:
        await consumer.stop()
        await service.aclose()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_end_to_end_handle_webhook_notification_against_mockserver(
    redis_client: Redis,
    mockserver_base_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bout-en-bout : Consumer -> handle_webhook_notification -> repositories ->
    _call_webhook_notification (httpx réel) -> MockServer -> XACK."""
    from document_ia_api.infra import webhook_notification_service as svc_mod

    stream = f"test_webhook_e2e:{uuid4()}"
    group = f"group-e2e-{uuid4()}"
    webhook_id = uuid4()
    execution_id = str(uuid4())
    webhook_dto = _make_webhook_dto(webhook_id, f"{mockserver_base_url}/webhook/ok")
    event_dto = _make_event_dto(execution_id)

    @asynccontextmanager
    async def fake_session():
        yield object()

    class FakeWebhookRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, _wid: UUID) -> WebHookDTO:
            return webhook_dto

    class FakeEventRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_last_event_by_execution_id(self, _eid: str) -> EventDTO:
            return event_dto

    monkeypatch.setattr(svc_mod.database_manager, "local_session", fake_session)
    monkeypatch.setattr(svc_mod, "WebHookRepository", FakeWebhookRepo)
    monkeypatch.setattr(svc_mod, "EventRepository", FakeEventRepo)

    service = WebhookNotificationService(retry_initial_delay_seconds=0.1)
    consumer = _make_api_consumer(
        stream_name=stream,
        consumer_group=group,
        message_class=WebHookMessage,
        handler=service.handle_webhook_notification,
    )
    service.bind_stop_event(consumer.stop_flag)

    await _append_message(
        redis_client,
        stream,
        WebHookMessage(workflow_execution_id=execution_id, webhook_id=webhook_id),
    )

    await consumer.start()
    try:
        await _wait_until(lambda: service._http_client is not None, timeout=5)
        await _wait_until(_pending_is_zero_pred(redis_client, stream, group), timeout=5)
        assert await _dlq_len(redis_client, stream) == 0
    finally:
        await consumer.stop()
        await service.aclose()
        await redis_client.delete(stream, f"{stream}:dlq")
