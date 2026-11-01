from unittest.mock import AsyncMock

import httpx
import pytest

from document_ia_api.infra.redis.webhook_error_policy import WebhookErrorPolicy


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
