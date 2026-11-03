"""Fixed-schema delivery events, suitable for counters in the log collector."""

import logging

logger = logging.getLogger(__name__)


def delivery_metric(stream: str, operation: str, outcome: str, value: int = 1) -> None:
    # Never accept payloads, exception messages or entry IDs as metric labels.
    logger.info(
        "redis_delivery stream=%s operation=%s outcome=%s value=%d",
        stream,
        operation,
        outcome,
        value,
    )
