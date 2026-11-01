"""Workflow failure policy: Redis requeue, bounded attempts, terminal DLQ.

Unlike webhook HTTP retries this policy never sleeps/retries the handler inline.
Delivery failures leave the original pending unless a terminal copy is confirmed.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.redis.failure_classification import classify_failure
from document_ia_infra.redis.delivery_metrics import delivery_metric
from document_ia_infra.redis.stream_delivery import StreamDelivery

logger = logging.getLogger(__name__)


class WorkerErrorPolicy:
    def __init__(self, max_attempts: int):
        self.max_attempts = max_attempts

    async def finish(
        self,
        future: asyncio.Future[Any],
        entry_id: str,
        fields: dict[str, Any],
        redis: Redis,
        delivery: StreamDelivery,
        requeue: Callable[..., Awaitable[bool]],
        retain: Callable[..., Awaitable[bool]],
    ) -> None:
        reason = ""
        error = ""
        try:
            future.result()
        except Exception as exc:
            category = classify_failure(exc)
            delivery_metric(delivery.stream, "failure", category)
            fields = {**fields, "failure_class": category}
            error = type(exc).__name__
            retries = int(fields.get("retries", "0"))
            if isinstance(exc, RetryableException) and retries < self.max_attempts - 1:
                try:
                    if not await requeue(
                        redis, entry_id, str(fields.get("data", "")), retries + 1
                    ):
                        return
                except Exception as exc:
                    reason, error = "error_requeueing_message", type(exc).__name__
            elif isinstance(exc, RetryableException):
                reason = "max_retries_exceeded"
            else:
                reason = "not_retryable_error"
        if reason and not await retain(redis, entry_id, fields, reason, error):
            return
        try:
            await delivery.ack(redis, entry_id)
        except Exception as exc:
            logger.error("ACK failed for message %s: %s", entry_id, type(exc).__name__)
