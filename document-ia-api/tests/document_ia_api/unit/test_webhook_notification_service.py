"""Unit tests for WebhookNotificationService and API webhook consumer wiring."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.exc import (
    DBAPIError,
    InterfaceError,
    OperationalError,
    TimeoutError as SATimeoutError,
)

from document_ia_api.infra.webhook_notification_service import (
    WebhookNotificationService,
)
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.webhook.dto.webhook_dto import WebHookDTO
from document_ia_infra.exception.entity_not_found_exception import (
    EntityNotFoundException,
)
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.redis.consumer import build_instance_consumer_name
from document_ia_infra.redis.model.webhook_message import WebHookMessage


@pytest.fixture(autouse=True)
def mock_api_key_service_auth() -> None:
    """Unit tests do not exercise API authentication or PostgreSQL."""


def _sample_webhook_dto(
    url: str = "https://example.test/webhook",
    headers: dict[str, str] | None = None,
) -> WebHookDTO:
    now = datetime.now(UTC)
    return WebHookDTO(
        id=uuid4(),
        organization_id=uuid4(),
        url=url,
        headers=headers if headers is not None else {"X-Custom": "value"},
        created_at=now,
        updated_at=now,
    )


def _sample_event_dto(execution_id: str) -> EventDTO:
    organization_id = uuid4()
    return EventDTO(
        id=uuid4(),
        workflow_id="wf-1",
        organization_id=organization_id,
        execution_id=execution_id,
        created_at=datetime.now(UTC),
        event_type=EventType.WORKFLOW_EXECUTION_STARTED,
        event={
            "workflow_id": "wf-1",
            "execution_id": execution_id,
            "organization_id": str(organization_id),
            "created_at": datetime.now(UTC).isoformat(),
            "version": 1,
            "s3_file_info": None,
            "file_url": "https://example.test/doc.pdf",
            "metadata": {},
            "classification_parameters": {},
            "extraction_parameters": {},
        },
    )


def test_api_instance_consumer_name_properties() -> None:
    name_a = build_instance_consumer_name("api-webhook-consumer")
    assert name_a == build_instance_consumer_name("api-webhook-consumer")
    assert name_a != build_instance_consumer_name("api-webhook-consumer-other")
    assert " " not in name_a


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (200, False),
        (204, False),
        (301, False),
        (302, False),
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (405, False),
        (410, False),
        (413, False),
        (415, False),
        (422, False),
        (408, True),
        (409, True),
        (425, True),
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
    ],
)
def test_should_retry_http_status(status_code: int, expected: bool) -> None:
    assert WebhookNotificationService.should_retry_http_status(status_code) is expected


def test_compute_backoff_delay_exponential_with_cap() -> None:
    service = WebhookNotificationService(
        retry_initial_delay_seconds=5.0,
        retry_backoff_multiplier=2.0,
        max_retry_delay_seconds=25.0,
    )
    assert service.compute_backoff_delay(0) == 5.0
    assert service.compute_backoff_delay(1) == 10.0
    assert service.compute_backoff_delay(2) == 20.0
    assert service.compute_backoff_delay(3) == 25.0


@pytest.mark.asyncio
async def test_call_webhook_notification_deduplicates_headers_and_reuses_client() -> (
    None
):
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"received": True})

    service = WebhookNotificationService(retry_initial_delay_seconds=0.0)
    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service._http_client = mock_client

    execution_id = str(uuid4())
    webhook_dto = _sample_webhook_dto(
        headers={
            "content-type": "application/cloudevents+json",
            "X-Signature": "sig-1",
        }
    )
    event_dto = _sample_event_dto(execution_id)

    await service._call_webhook_notification(webhook_dto, event_dto)
    await service._call_webhook_notification(webhook_dto, event_dto)

    assert len(captured_requests) == 2
    assert service._http_client is mock_client
    first_req = captured_requests[0]
    content_type_headers = [
        value
        for key, value in first_req.headers.multi_items()
        if key.lower() == "content-type"
    ]
    assert content_type_headers == ["application/cloudevents+json"]
    assert first_req.headers["X-Signature"] == "sig-1"
    body = json.loads(first_req.content.decode("utf-8"))
    assert body["id"] == execution_id
    assert body["status"] == "STARTED"

    await service.aclose()
    assert service._http_client is None
    assert mock_client.is_closed


@pytest.mark.asyncio
async def test_db_session_released_before_http_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La session SQLAlchemy doit être refermée avant l'appel HTTP sortant afin
    de ne jamais immobiliser le pool PostgreSQL pendant le timeout HTTP (30s)
    ou le backoff."""
    from document_ia_api.infra import webhook_notification_service as svc_mod

    session_open = False
    observed_session_open_during_http: list[bool] = []
    webhook_dto = _sample_webhook_dto()
    execution_id = str(uuid4())
    event_dto = _sample_event_dto(execution_id)

    @asynccontextmanager
    async def tracked_session():
        nonlocal session_open
        session_open = True
        try:
            yield object()
        finally:
            session_open = False

    class FakeWebhookRepo:
        def __init__(self, _session: Any) -> None:
            assert session_open is True

        async def get_by_id(self, _wid: Any) -> WebHookDTO:
            return webhook_dto

    class FakeEventRepo:
        def __init__(self, _session: Any) -> None:
            assert session_open is True

        async def get_last_event_by_execution_id(self, _eid: str) -> EventDTO:
            return event_dto

    monkeypatch.setattr(svc_mod.database_manager, "local_session", tracked_session)
    monkeypatch.setattr(svc_mod, "WebHookRepository", FakeWebhookRepo)
    monkeypatch.setattr(svc_mod, "EventRepository", FakeEventRepo)

    service = WebhookNotificationService(retry_initial_delay_seconds=0.0)

    async def fake_call_http(_wh: WebHookDTO, _ev: EventDTO) -> None:
        observed_session_open_during_http.append(session_open)

    monkeypatch.setattr(service, "_call_webhook_notification", fake_call_http)

    await service.handle_webhook_notification(
        WebHookMessage(workflow_execution_id=execution_id, webhook_id=webhook_dto.id)
    )

    assert observed_session_open_during_http == [False]


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 500, 503])
async def test_retryable_http_status_sleeps_until_last_retry_and_raises_retryable(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(
        "document_ia_api.infra.webhook_notification_service.asyncio.sleep",
        record_sleep,
    )

    service = WebhookNotificationService(
        retry_initial_delay_seconds=2.0,
        retry_backoff_multiplier=3.0,
    )
    webhook_dto = _sample_webhook_dto()
    event_dto = _sample_event_dto(str(uuid4()))

    async def fail_http(_wh: WebHookDTO, _ev: EventDTO) -> None:
        req = httpx.Request("POST", webhook_dto.url)
        resp = httpx.Response(status_code, request=req)
        raise httpx.HTTPStatusError("upstream error", request=req, response=resp)

    monkeypatch.setattr(service, "_call_webhook_notification", fail_http)

    with pytest.raises(RetryableException):
        await service._deliver_webhook_with_retry_policy(
            webhook_dto, event_dto, retry_count=1, is_last_retry=False
        )
    assert sleeps == [6.0]

    # Sur la dernière tentative, pas d'attente inutile avant l'envoi en DLQ
    sleeps.clear()
    with pytest.raises(RetryableException):
        await service._deliver_webhook_with_retry_policy(
            webhook_dto, event_dto, retry_count=3, is_last_retry=True
        )
    assert sleeps == []


@pytest.mark.asyncio
async def test_bind_stop_event_interrupts_retry_backoff_immediately() -> None:
    """Lorsqu'un arrêt gracieux est déclenché pendant un backoff HTTP, l'attente
    s'interrompt immédiatement et lève RetryableException pour permettre au
    consumer de remettre en file et d'acquitter sans attendre le timeout."""
    stop_event = asyncio.Event()
    service = WebhookNotificationService(
        retry_initial_delay_seconds=30.0,
        max_retry_delay_seconds=30.0,
    )
    service.bind_stop_event(stop_event)

    webhook_dto = _sample_webhook_dto()
    event_dto = _sample_event_dto(str(uuid4()))

    async def fail_503(_wh: WebHookDTO, _ev: EventDTO) -> None:
        req = httpx.Request("POST", webhook_dto.url)
        resp = httpx.Response(503, request=req)
        raise httpx.HTTPStatusError("service unavailable", request=req, response=resp)

    service._call_webhook_notification = fail_503  # type: ignore[method-assign]

    async def trigger_stop_shortly() -> None:
        await asyncio.sleep(0.05)
        stop_event.set()

    stopper = asyncio.create_task(trigger_stop_shortly())
    start = monotonic()
    try:
        with pytest.raises(RetryableException):
            await service._deliver_webhook_with_retry_policy(
                webhook_dto, event_dto, retry_count=0, is_last_retry=False
            )
    finally:
        await stopper

    assert monotonic() - start < 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
async def test_non_retryable_http_status_reraises_without_sleeping(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(
        "document_ia_api.infra.webhook_notification_service.asyncio.sleep",
        record_sleep,
    )

    service = WebhookNotificationService(retry_initial_delay_seconds=5.0)
    webhook_dto = _sample_webhook_dto()
    event_dto = _sample_event_dto(str(uuid4()))

    async def fail_http(_wh: WebHookDTO, _ev: EventDTO) -> None:
        req = httpx.Request("POST", webhook_dto.url)
        resp = httpx.Response(status_code, request=req)
        raise httpx.HTTPStatusError("rejected", request=req, response=resp)

    monkeypatch.setattr(service, "_call_webhook_notification", fail_http)

    with pytest.raises(httpx.HTTPStatusError):
        await service._deliver_webhook_with_retry_policy(
            webhook_dto, event_dto, retry_count=0, is_last_retry=False
        )
    assert sleeps == []


@pytest.mark.asyncio
@pytest.mark.parametrize("exc_cls", [httpx.ConnectError, httpx.ReadTimeout])
async def test_transport_error_raises_retryable_exception(
    monkeypatch: pytest.MonkeyPatch,
    exc_cls: type[httpx.TransportError],
) -> None:
    service = WebhookNotificationService(retry_initial_delay_seconds=0.0)
    webhook_dto = _sample_webhook_dto()
    event_dto = _sample_event_dto(str(uuid4()))

    async def fail_transport(_wh: WebHookDTO, _ev: EventDTO) -> None:
        req = httpx.Request("POST", webhook_dto.url)
        raise exc_cls("network error", request=req)

    monkeypatch.setattr(service, "_call_webhook_notification", fail_transport)

    with pytest.raises(RetryableException):
        await service._deliver_webhook_with_retry_policy(
            webhook_dto, event_dto, retry_count=0, is_last_retry=False
        )


@pytest.mark.asyncio
async def test_transient_db_and_pool_errors_raise_retryable_and_non_transient_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from document_ia_api.infra import webhook_notification_service as svc_mod

    service = WebhookNotificationService(retry_initial_delay_seconds=0.0)
    msg = WebHookMessage(workflow_execution_id=str(uuid4()), webhook_id=uuid4())

    for transient_exc in (
        OperationalError("SELECT 1", {}, ConnectionError("db down")),
        InterfaceError("SELECT 1", {}, ConnectionError("connection closed")),
        SATimeoutError("QueuePool limit of size 5 overflow 10 reached"),
    ):

        def raise_transient(exc: Exception = transient_exc):
            raise exc

        monkeypatch.setattr(svc_mod.database_manager, "local_session", raise_transient)
        with pytest.raises(RetryableException):
            await service.handle_webhook_notification(
                msg, retry_count=0, is_last_retry=False
            )

    def raise_non_invalidated_dbapi_error():
        raise DBAPIError(
            "SELECT bad_col",
            {},
            RuntimeError("syntax error"),
            connection_invalidated=False,
        )

    monkeypatch.setattr(
        svc_mod.database_manager, "local_session", raise_non_invalidated_dbapi_error
    )
    with pytest.raises(DBAPIError):
        await service.handle_webhook_notification(
            msg, retry_count=0, is_last_retry=False
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["webhook", "event"])
async def test_missing_entity_raises_entity_not_found_non_retryable(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    from document_ia_api.infra import webhook_notification_service as svc_mod

    execution_id = str(uuid4())
    webhook_dto = _sample_webhook_dto()
    event_dto = _sample_event_dto(execution_id)

    @asynccontextmanager
    async def dummy_session():
        yield object()

    class FakeWebhookRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, _wid: Any) -> WebHookDTO | None:
            return None if missing == "webhook" else webhook_dto

    class FakeEventRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_last_event_by_execution_id(self, _eid: str) -> EventDTO | None:
            return None if missing == "event" else event_dto

    monkeypatch.setattr(svc_mod.database_manager, "local_session", dummy_session)
    monkeypatch.setattr(svc_mod, "WebHookRepository", FakeWebhookRepo)
    monkeypatch.setattr(svc_mod, "EventRepository", FakeEventRepo)

    service = WebhookNotificationService(retry_initial_delay_seconds=0.0)
    with pytest.raises(EntityNotFoundException):
        await service.handle_webhook_notification(
            WebHookMessage(
                workflow_execution_id=execution_id, webhook_id=webhook_dto.id
            )
        )


@pytest.mark.asyncio
async def test_api_lifespan_wires_webhook_consumer_and_cleans_up_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from document_ia_api import main as api_main

    created_consumers: list[Any] = []
    bound_events: list[asyncio.Event | None] = []

    class FakeConsumer[T]:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.stop_flag = asyncio.Event()
            self.started = False
            self.stopped = False
            created_consumers.append(self)

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

    @asynccontextmanager
    async def dummy_session():
        yield object()

    monkeypatch.setattr(api_main.s3_service, "check_connectivity", AsyncMock())
    monkeypatch.setattr(api_main.redis_service, "check_connectivity", AsyncMock())
    monkeypatch.setattr(api_main.database_manager, "local_session", dummy_session)
    monkeypatch.setattr(
        api_main.database_service, "check_database_connectivity", AsyncMock()
    )
    monkeypatch.setattr(api_main.migration_service, "auto_migrate", AsyncMock())
    monkeypatch.setattr(
        api_main.migration_service, "auto_migrate_analytics", AsyncMock()
    )
    monkeypatch.setattr(api_main, "AsyncIoConsumer", FakeConsumer)
    monkeypatch.setattr(
        api_main.webhook_notification_service,
        "bind_stop_event",
        lambda ev: bound_events.append(ev),
    )
    aclose_mock = AsyncMock()
    redis_close_mock = AsyncMock()
    db_dispose_mock = AsyncMock()
    monkeypatch.setattr(api_main.webhook_notification_service, "aclose", aclose_mock)
    monkeypatch.setattr(api_main.redis_service, "close", redis_close_mock)
    monkeypatch.setattr(api_main.database_manager, "dispose_async", db_dispose_mock)

    async with api_main.lifespan(api_main.app):
        assert len(created_consumers) == 1
        fake = created_consumers[0]
        assert fake.started is True
        assert "worker_number" not in fake.kwargs
        assert "execution_mode" not in fake.kwargs
        assert fake.kwargs["batch_size"] == 50
        assert fake.kwargs["reclaim_poll_interval_s"] == 5.0
        assert bound_events == [fake.stop_flag]

    assert created_consumers[0].stopped is True
    assert bound_events[-1] is None
    aclose_mock.assert_awaited_once()
    redis_close_mock.assert_awaited_once()
    db_dispose_mock.assert_awaited_once()
