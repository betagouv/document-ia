"""Integration tests for SimpleStreamConsumer retry behaviour against the mock server."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from time import monotonic
from typing import Awaitable, Callable
from uuid import uuid4

import httpx
import pytest
from redis.asyncio import Redis

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


async def _wait_until(predicate: Callable[[], Awaitable[bool]] | Callable[[], bool], *, timeout: float = 5.0, interval: float = 0.05) -> None:
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


def _pending_is_zero_pred(redis: Redis, stream: str, group: str) -> Callable[[], Awaitable[bool]]:
    async def _predicate() -> bool:
        return (await _pending_count(redis, stream, group)) == 0

    return _predicate


def _dlq_len_is_pred(redis: Redis, stream: str, expected: int) -> Callable[[], Awaitable[bool]]:
    async def _predicate() -> bool:
        return (await _dlq_len(redis, stream)) == expected

    return _predicate


async def _append_message(redis: Redis, stream: str, message: TestWebhookMessage) -> None:
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
            response = await client.post(dto["url"], headers=dto["headers"], json=dto["payload"])
            response.raise_for_status()

    return _handler


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

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
async def test_consumer_acknowledges_success(redis_client: Redis, mockserver_base_url: str) -> None:
    stream = f"test_webhook_stream_ok:{uuid4()}"
    group = f"group-ok-{uuid4()}"
    consumer = SimpleStreamConsumer[
        TestWebhookMessage
    ](
        stream_name=stream,
        handler=_webhook_handler_factory(),
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
    await consumer.start()

    await _wait_until(_pending_is_zero_pred(redis_client, stream, group))
    await _wait_until(_dlq_len_is_pred(redis_client, stream, expected=0))

    await consumer.stop()
    await redis_client.delete(stream)
    await redis_client.delete(f"{stream}:dlq")


@pytest.mark.asyncio
async def test_consumer_retries_then_dlq_on_429(redis_client: Redis, mockserver_base_url: str) -> None:
    stream = f"test_webhook_stream_ko:{uuid4()}"
    group = f"group-ko-{uuid4()}"
    consumer = SimpleStreamConsumer[
        TestWebhookMessage
    ](
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
async def test_consumer_immediate_dlq_on_401(redis_client: Redis, mockserver_base_url: str) -> None:
    stream = f"test_webhook_stream_unauthorized:{uuid4()}"
    group = f"group-unauth-{uuid4()}"
    consumer = SimpleStreamConsumer[
        TestWebhookMessage
    ](
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
