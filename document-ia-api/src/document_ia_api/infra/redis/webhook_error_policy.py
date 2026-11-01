"""Webhook HTTP backoff, separate from Redis delivery/recovery attempts."""

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from document_ia_infra.redis.failure_classification import classify_failure


class WebhookErrorPolicy:
    def __init__(self, max_retries: int, initial_delay: float, multiplier: float):
        # HTTP max_retries means additional inline attempts, NOT the Redis
        # recovery policy's total delivery attempts. Preserve that distinction.
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.multiplier = multiplier

    @staticmethod
    def should_retry(status: int) -> bool:
        return status in {408, 425, 429} or 500 <= status < 600

    def delay(self, attempt: int) -> float:
        return self.initial_delay * self.multiplier**attempt

    async def handle(
        self,
        handler: Callable[[], Awaitable[None]],
        retain: Callable[[str], Awaitable[bool]],
    ) -> bool:
        attempt = 0
        while True:
            try:
                await handler()
                return True
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if classify_failure(exc) != "temporary":
                    return await retain(f"Non retryable HTTP {status}")
                if attempt >= self.max_retries:
                    return await retain(f"Max retries exceeded (HTTP {status})")
                delay = self.delay(attempt)
                attempt += 1
                await asyncio.sleep(delay)
        # Non-HTTP failures propagate to the consumer and remain pending.
