"""
Hiérarchie de consommateurs Redis Stream.

Ce module réexporte BaseConsumer, ThreadConsumer et AsyncIoConsumer
depuis leurs modules dédiés respectifs pour préserver la compatibilité
des imports :
- :class:`BaseConsumer` depuis ``base_consumer``
- :class:`ThreadConsumer` depuis ``thread_consumer``
- :class:`AsyncIoConsumer` depuis ``asyncio_consumer``
"""

from document_ia_infra.redis.asyncio_consumer import AsyncIoConsumer
from document_ia_infra.redis.base_consumer import (
    DLQ_SCAN_BATCH_SIZE,
    RECLAIM_IDLE_MS,
    BaseConsumer,
    build_instance_consumer_name,
)
from document_ia_infra.redis.thread_consumer import ThreadConsumer

Consumer = ThreadConsumer

__all__ = [
    "AsyncIoConsumer",
    "BaseConsumer",
    "Consumer",
    "DLQ_SCAN_BATCH_SIZE",
    "RECLAIM_IDLE_MS",
    "ThreadConsumer",
    "build_instance_consumer_name",
]
