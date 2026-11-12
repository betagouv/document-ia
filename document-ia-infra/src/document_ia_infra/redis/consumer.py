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
from document_ia_infra.redis.handler_execution import (
    HandlerExecution,
    run_handler_in_thread,
)
from document_ia_infra.redis.progress_tracker import (
    ProgressTracker,
    get_current_progress_tracker,
    record_step_progress,
)
from document_ia_infra.redis.stream_delivery import StreamDelivery
from document_ia_infra.redis.thread_consumer import ThreadConsumer
from document_ia_infra.redis.worker_error_policy import WorkerErrorPolicy

Consumer = ThreadConsumer

__all__ = [
    "AsyncIoConsumer",
    "BaseConsumer",
    "Consumer",
    "DLQ_SCAN_BATCH_SIZE",
    "HandlerExecution",
    "ProgressTracker",
    "RECLAIM_IDLE_MS",
    "StreamDelivery",
    "ThreadConsumer",
    "WorkerErrorPolicy",
    "build_instance_consumer_name",
    "get_current_progress_tracker",
    "record_step_progress",
    "run_handler_in_thread",
]
