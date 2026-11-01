from unittest.mock import AsyncMock, MagicMock
import logging
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from document_ia_api.infra.redis.webhook_error_policy import WebhookErrorPolicy
from document_ia_api.infra.redis.simple_stream_consumer import SimpleStreamConsumer
from document_ia_infra.redis.model.webhook_message import WebHookMessage
import document_ia_api.infra.webhook_notification_service as service_module


@pytest.fixture(autouse=True)
def mock_api_key_service_auth():
    """Policy tests exercise no API authentication or database operations."""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,retry",
    [
        (400, False),
        (401, False),
        (404, False),
        (409, False),
        (408, True),
        (425, True),
        (429, True),
        (500, True),
        (503, True),
    ],
)
async def test_webhook_status_controls_bounded_retry(status, retry):
    error = httpx.HTTPStatusError(
        "private",
        request=httpx.Request("POST", "https://example.test"),
        response=httpx.Response(status),
    )
    handler = AsyncMock(side_effect=error)
    retain = AsyncMock(return_value=True)
    policy = WebhookErrorPolicy(max_retries=1, initial_delay=0, multiplier=1)
    assert policy.should_retry(status) is retry
    assert await policy.handle(handler, retain)
    assert handler.await_count == (2 if retry else 1)
    retain.assert_awaited_once()
    assert "private" not in retain.await_args.args[0]


@pytest.mark.asyncio
async def test_webhook_retention_failure_never_authorizes_ack():
    error = httpx.HTTPStatusError(
        "private",
        request=httpx.Request("POST", "https://example.test"),
        response=httpx.Response(401),
    )
    assert not await WebhookErrorPolicy(1, 0, 1).handle(
        AsyncMock(side_effect=error),
        AsyncMock(return_value=False),
    )


@pytest.mark.asyncio
async def test_consumer_logs_handler_error_class_not_contents(caplog):
    async def fail(message):
        consumer._stop_event.set()
        raise RuntimeError("SECRET-DOCUMENT https://secret.example/?token=secret")

    consumer = SimpleStreamConsumer(
        stream_name="hooks",
        consumer_group="group",
        consumer_name="worker",
        handler=fail,
        message_class=WebHookMessage,
    )
    redis = AsyncMock()
    consumer._redis = redis
    response = [
        (
            "hooks",
            [
                (
                    "1-0",
                    {
                        "data": '{"webhook_id":"00000000-0000-0000-0000-000000000001","workflow_execution_id":"execution"}'
                    },
                ),
            ],
        )
    ]

    async def read_once(*args, **kwargs):
        consumer._stop_event.set()
        return response

    consumer._delivery.read = AsyncMock(side_effect=read_once)
    with caplog.at_level(logging.INFO):
        await consumer._run()
    assert "Handler error" in caplog.text and "RuntimeError" in caplog.text
    assert "SECRET-DOCUMENT" not in caplog.text
    assert "secret.example" not in caplog.text
    redis.xack.assert_not_awaited()


@pytest.mark.asyncio
async def test_consumer_logs_dlq_outcome_without_error_message(caplog):
    consumer = SimpleStreamConsumer(
        stream_name="hooks",
        consumer_group="group",
        consumer_name="worker",
        handler=AsyncMock(),
        message_class=WebHookMessage,
    )
    consumer._already_retained_in_dlq = AsyncMock(return_value=False)
    consumer._delivery.copy_once = AsyncMock(return_value=True)
    with caplog.at_level(logging.INFO):
        assert await consumer._send_to_dlq(
            AsyncMock(), "hooks", "1-0", {"data": "SECRET-DOCUMENT"}, "SECRET-ERROR"
        )
    assert "moved to DLQ" in caplog.text
    assert "SECRET-" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["scan", "write"])
async def test_consumer_logs_retention_error_class_only(caplog, operation):
    consumer = SimpleStreamConsumer(
        stream_name="hooks",
        consumer_group="group",
        consumer_name="worker",
        handler=AsyncMock(),
        message_class=WebHookMessage,
    )
    consumer._already_retained_in_dlq = AsyncMock(return_value=False)
    consumer._delivery.copy_once = AsyncMock(return_value=True)
    target = (
        consumer._already_retained_in_dlq
        if operation == "scan"
        else consumer._delivery.copy_once
    )
    target.side_effect = RuntimeError("SECRET-ERROR")
    with caplog.at_level(logging.INFO):
        assert not await consumer._send_to_dlq(
            AsyncMock(), "hooks", "1-0", {"data": "SECRET-DOCUMENT"}, "private"
        )
    assert "RuntimeError" in caplog.text
    assert "SECRET-" not in caplog.text


@pytest.mark.asyncio
async def test_webhook_service_logs_failure_class_only(monkeypatch, caplog):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=MagicMock())
    session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        service_module.database_manager, "local_session", lambda: session
    )
    monkeypatch.setattr(
        service_module.WebHookRepository, "get_by_id", AsyncMock(return_value=object())
    )
    monkeypatch.setattr(
        service_module.EventRepository,
        "get_last_event_by_execution_id",
        AsyncMock(return_value=object()),
    )
    service = service_module.WebhookNotificationService()
    service._call_webhook_notification = AsyncMock(
        side_effect=RuntimeError("SECRET-DOCUMENT")
    )
    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError):
        await service.handle_webhook_notification(WebHookMessage("execution", uuid4()))
    assert "Error handling webhook notification: RuntimeError" in caplog.text
    assert "SECRET-DOCUMENT" not in caplog.text


@pytest.mark.asyncio
async def test_webhook_service_does_not_log_target_url_or_payload(monkeypatch, caplog):
    url = "https://secret.example/?token=secret"
    client = MagicMock()
    client.post = AsyncMock(
        return_value=httpx.Response(200, request=httpx.Request("POST", url))
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(service_module.httpx, "AsyncClient", lambda **kwargs: context)
    monkeypatch.setattr(
        service_module.ExecutionService,
        "get_event_model",
        lambda *args, **kwargs: SimpleNamespace(
            model_dump_json=lambda: "SECRET-DOCUMENT"
        ),
    )
    with caplog.at_level(logging.INFO):
        await service_module.WebhookNotificationService()._call_webhook_notification(
            SimpleNamespace(url=url, headers={}),
            SimpleNamespace(execution_id="execution"),
        )
    assert "Webhook notification sent successfully with status 200" in caplog.text
    assert "secret.example" not in caplog.text and "SECRET-DOCUMENT" not in caplog.text
    assert client.post.await_args.args[0] == url
    assert client.post.await_args.kwargs["content"] == "SECRET-DOCUMENT"
