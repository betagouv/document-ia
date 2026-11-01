"""Integration tests for SimpleStreamConsumer retry behaviour against the mock server."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from time import monotonic
from typing import Any, Awaitable, Callable
from uuid import uuid4

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.exc import OperationalError

from document_ia_api.infra.redis.simple_stream_consumer import SimpleStreamConsumer
from document_ia_infra.redis.serializable_message import SerializableMessage


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass
class TestWebhookMessage(SerializableMessage):
    workflow_execution_id: str
    webhook_url: str

    def to_dict(self) -> dict[str, str]:
        return {
            "workflow_execution_id": self.workflow_execution_id,
            "webhook_url": self.webhook_url,
        }

    @staticmethod
    def from_json(data: str) -> "TestWebhookMessage":
        payload = json.loads(data)
        return TestWebhookMessage(
            workflow_execution_id=payload["workflow_execution_id"],
            webhook_url=payload["webhook_url"],
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
    redis: Redis, stream: str, message: TestWebhookMessage
) -> None:
    await redis.xadd(stream, {"data": json.dumps(message.to_dict())})


async def _dlq_len(redis: Redis, stream: str) -> int:
    return await redis.xlen(f"{stream}:dlq")


async def _pending_count(redis: Redis, stream: str, group: str) -> int:
    info = await redis.xpending(stream, group)
    return info["pending"] if isinstance(info, dict) else info.pending


def _webhook_handler_factory() -> Callable[[TestWebhookMessage], Awaitable[None]]:
    async def _handler(message: TestWebhookMessage) -> None:
        dto = {
            "url": message.webhook_url,
            "headers": {"X-Workflow-Execution": message.workflow_execution_id},
            "payload": {"execution_id": message.workflow_execution_id},
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                dto["url"], headers=dto["headers"], json=dto["payload"]
            )
            response.raise_for_status()

    return _handler


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_api_key_service_auth() -> None:
    """Consumer integration tests do not exercise API authentication or the DB."""


@pytest.fixture(autouse=True)
def use_test_redis(monkeypatch: pytest.MonkeyPatch, redis_client: Redis) -> None:
    from document_ia_infra.redis import redis_manager as redis_manager_module

    async def get_connection() -> Redis:
        return redis_client

    monkeypatch.setattr(
        redis_manager_module.redis_manager, "get_connection", get_connection
    )


@pytest.fixture
async def redis_client() -> Redis:
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consumer_acknowledges_success(
    redis_client: Redis,
    mockserver_base_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = f"test_webhook_stream_ok:{uuid4()}"
    group = f"group-ok-{uuid4()}"
    handler_called = asyncio.Event()
    original_handler = _webhook_handler_factory()

    async def record_handler(message: TestWebhookMessage) -> None:
        await original_handler(message)
        handler_called.set()

    consumer = SimpleStreamConsumer[TestWebhookMessage](
        stream_name=stream,
        handler=record_handler,
        message_class=TestWebhookMessage,
        consumer_group=group,
        consumer_name=f"consumer-ok-{uuid4()}",
        max_retries=2,
        retry_initial_delay_seconds=0.1,
        retry_backoff_multiplier=2.0,
    )

    message = TestWebhookMessage(
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
        await asyncio.wait_for(handler_called.wait(), timeout=2)
        await asyncio.wait_for(acknowledged.wait(), timeout=2)
        assert await _pending_count(redis_client, stream, group) == 0
        assert await _dlq_len(redis_client, stream) == 0
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
@pytest.mark.parametrize("error_class", [httpx.ReadTimeout, httpx.ConnectError])
async def test_consumer_leaves_http_transport_failure_pending(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
    error_class: type[httpx.TransportError],
) -> None:
    stream = f"test_webhook_transport:{uuid4()}"
    group = f"group-transport-{uuid4()}"
    handler_called = asyncio.Event()

    async def fail_transport(message: TestWebhookMessage) -> None:
        handler_called.set()
        request = httpx.Request("POST", message.webhook_url)
        raise error_class("webhook transport failed", request=request)

    consumer = SimpleStreamConsumer[TestWebhookMessage](
        stream_name=stream,
        handler=fail_transport,
        message_class=TestWebhookMessage,
        consumer_group=group,
        consumer_name=f"consumer-transport-{uuid4()}",
        block_ms=10,
    )
    message = TestWebhookMessage(
        workflow_execution_id=str(uuid4()),
        webhook_url="http://localhost:1080/webhook",
    )
    await _append_message(redis_client, stream, message)
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
    await consumer.start()
    try:
        await asyncio.wait_for(handler_called.wait(), timeout=2)
        await asyncio.wait_for(next_read_started.wait(), timeout=2)
        assert await _pending_count(redis_client, stream, group) == 1
        assert await _dlq_len(redis_client, stream) == 0
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_consumer_leaves_database_failure_pending(
    redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = f"test_webhook_database:{uuid4()}"
    group = f"group-database-{uuid4()}"
    handler_called = asyncio.Event()

    from document_ia_api.infra import webhook_notification_service as service_module

    def fail_database_session() -> None:
        handler_called.set()
        raise OperationalError("connect", {}, ConnectionError("database unavailable"))

    monkeypatch.setattr(
        service_module.database_manager, "local_session", fail_database_session
    )
    message = TestWebhookMessage(
        workflow_execution_id=str(uuid4()),
        webhook_url="http://localhost:1080/webhook",
    )
    consumer = SimpleStreamConsumer[TestWebhookMessage](
        stream_name=stream,
        handler=service_module.webhook_notification_service.handle_webhook_notification,
        message_class=TestWebhookMessage,
        consumer_group=group,
        consumer_name=f"consumer-database-{uuid4()}",
        block_ms=10,
    )
    await _append_message(redis_client, stream, message)
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
    await consumer.start()
    try:
        await asyncio.wait_for(handler_called.wait(), timeout=2)
        await asyncio.wait_for(next_read_started.wait(), timeout=2)
        assert await _pending_count(redis_client, stream, group) == 1
        assert await _dlq_len(redis_client, stream) == 0
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_consumer_leaves_invalid_json_pending(
    redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = f"test_webhook_invalid_json:{uuid4()}"
    group = f"group-invalid-json-{uuid4()}"
    decode_attempted = asyncio.Event()

    class InvalidJsonMessage(TestWebhookMessage):
        @staticmethod
        def from_json(data: str) -> TestWebhookMessage:
            decode_attempted.set()
            return TestWebhookMessage.from_json(data)

    async def should_not_run(message: TestWebhookMessage) -> None:
        pytest.fail("Invalid JSON must not reach the webhook handler")

    consumer = SimpleStreamConsumer[TestWebhookMessage](
        stream_name=stream,
        handler=should_not_run,
        message_class=InvalidJsonMessage,
        consumer_group=group,
        consumer_name=f"consumer-invalid-json-{uuid4()}",
        block_ms=10,
    )
    await redis_client.xadd(stream, {"data": "{invalid-json}"})
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
    await consumer.start()
    try:
        await asyncio.wait_for(decode_attempted.wait(), timeout=2)
        await asyncio.wait_for(next_read_started.wait(), timeout=2)
        assert await _pending_count(redis_client, stream, group) == 1
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

    async def reject_webhook(message: TestWebhookMessage) -> None:
        request = httpx.Request("POST", message.webhook_url)
        response = httpx.Response(400, request=request)
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    consumer = SimpleStreamConsumer[TestWebhookMessage](
        stream_name=stream,
        handler=reject_webhook,
        message_class=TestWebhookMessage,
        consumer_group=group,
        consumer_name=f"consumer-terminal-{uuid4()}",
        block_ms=10,
    )
    original_eval = redis_client.eval
    operations: list[str] = []

    async def record_dlq_attempt(script: str, numkeys: int, *args: Any) -> Any:
        # Retention is now a shared atomic scan+XADD Lua operation.
        stream_name = args[0]
        operations.append(f"retain:{stream_name}")
        if stream_name == f"{stream}:dlq":
            dlq_attempted.set()
            if not dlq_available:
                raise ConnectionError("DLQ unavailable")
        return await original_eval(script, numkeys, *args)

    message = TestWebhookMessage(
        workflow_execution_id=str(uuid4()),
        webhook_url="http://localhost:1080/webhook",
    )
    await _append_message(redis_client, stream, message)
    monkeypatch.setattr(redis_client, "eval", record_dlq_attempt)
    original_xack = redis_client.xack

    async def record_ack(stream_name: str, group_name: str, entry_id: str) -> int:
        operations.append(f"xack:{stream_name}")
        return await original_xack(stream_name, group_name, entry_id)

    monkeypatch.setattr(redis_client, "xack", record_ack)
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
    await consumer.start()
    try:
        await asyncio.wait_for(dlq_attempted.wait(), timeout=2)
        await asyncio.wait_for(next_read_started.wait(), timeout=2)

        async def reached_expected_state() -> bool:
            pending = await _pending_count(redis_client, stream, group)
            dlq_length = await _dlq_len(redis_client, stream)
            if dlq_available:
                return pending == 0 and dlq_length == 1
            return pending == 1 and dlq_length == 0

        await _wait_until(reached_expected_state)
        if dlq_available:
            assert operations == [f"retain:{stream}:dlq", f"xack:{stream}"]
        else:
            assert operations == [f"retain:{stream}:dlq"]
    finally:
        await consumer.stop()
        await redis_client.delete(stream, f"{stream}:dlq")


@pytest.mark.asyncio
async def test_consumer_retries_then_dlq_on_429(
    redis_client: Redis, mockserver_base_url: str
) -> None:
    stream = f"test_webhook_stream_ko:{uuid4()}"
    group = f"group-ko-{uuid4()}"
    consumer = SimpleStreamConsumer[TestWebhookMessage](
        stream_name=stream,
        handler=_webhook_handler_factory(),
        message_class=TestWebhookMessage,
        consumer_group=group,
        consumer_name=f"consumer-ko-{uuid4()}",
        max_retries=1,
        retry_initial_delay_seconds=1.0,
        retry_backoff_multiplier=1.0,
    )

    message = TestWebhookMessage(
        workflow_execution_id=str(uuid4()),
        webhook_url=f"{mockserver_base_url}/webhook/ko",
    )

    await _append_message(redis_client, stream, message)
    await consumer.start()

    start = monotonic()

    await _wait_until(_dlq_len_is_pred(redis_client, stream, expected=1), timeout=10)
    elapsed = monotonic() - start
    assert elapsed >= 1.0, "Expected at least one retry delay before DLQ"

    await _wait_until(_pending_is_zero_pred(redis_client, stream, group))

    await consumer.stop()
    await redis_client.delete(stream)
    await redis_client.delete(f"{stream}:dlq")


@pytest.mark.asyncio
async def test_consumer_immediate_dlq_on_401(
    redis_client: Redis, mockserver_base_url: str
) -> None:
    stream = f"test_webhook_stream_unauthorized:{uuid4()}"
    group = f"group-unauth-{uuid4()}"
    consumer = SimpleStreamConsumer[TestWebhookMessage](
        stream_name=stream,
        handler=_webhook_handler_factory(),
        message_class=TestWebhookMessage,
        consumer_group=group,
        consumer_name=f"consumer-unauth-{uuid4()}",
        max_retries=3,
        retry_initial_delay_seconds=0.5,
        retry_backoff_multiplier=2.0,
    )

    message = TestWebhookMessage(
        workflow_execution_id=str(uuid4()),
        webhook_url=f"{mockserver_base_url}/webhook/kko",
    )

    await _append_message(redis_client, stream, message)
    await consumer.start()

    await _wait_until(_dlq_len_is_pred(redis_client, stream, expected=1))
    await _wait_until(_pending_is_zero_pred(redis_client, stream, group))

    await consumer.stop()
    await redis_client.delete(stream)
    await redis_client.delete(f"{stream}:dlq")
