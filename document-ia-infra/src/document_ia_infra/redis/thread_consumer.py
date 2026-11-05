"""
Consommateur Redis Stream multi-thread (ThreadConsumer).
"""

import asyncio
import functools
import logging
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

from document_ia_infra.redis.base_consumer import BaseConsumer
from document_ia_infra.redis.handler_execution import (
    HandlerExecution,
    run_handler_in_thread,
)
from document_ia_infra.redis.progress_tracker import (
    ProgressTracker,
    current_progress_tracker,
)
from document_ia_infra.redis.redis_manager import RedisManager
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_infra.redis.serializable_message import SerializableMessage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SerializableMessage)

__all__ = [
    "ThreadConsumer",
]


class ThreadConsumer(BaseConsumer[T]):
    """Consommateur Redis Stream multi-thread (adapté aux traitements CPU-bound du worker).

    Chaque message est exécuté dans un ``ThreadPoolExecutor`` initialisé à la demande,
    avec une boucle ``asyncio`` dédiée par thread et un nettoyage complet des tâches
    et générateurs asynchrones en fin d'exécution.
    """

    def __init__(
        self,
        consumer_name: str,
        consumer_group: str,
        stream_name: str,
        batch_size: int,
        block_time: int,
        message_class: type[T],
        process_message_callable: Callable[[T, int, bool], Coroutine[Any, Any, None]],
        worker_number: int = redis_settings.REDIS_WORKER_NUMBER,
        max_retry_number: int = 3,
        *,
        start_from: str = "0-0",
        reclaim_idle_ms: int | None = None,
        reclaim_batch_size: int | None = None,
        reclaim_poll_interval_s: float = 1.0,
        drain_timeout_s: float = 10.0,
        stream_maxlen: int | None = redis_settings.EVENT_STREAM_MAXLEN,
        dlq_maxlen: int | None = redis_settings.DLQ_STREAM_MAXLEN,
        close_redis_on_stop: bool = True,
        current_redis_manager: RedisManager | None = None,
        max_processing_time_s: float | None = None,
        step_progress_timeout_s: float | None = None,
        use_execution_lease: bool = False,
        lease_ttl_ms: int | None = None,
    ) -> None:
        if worker_number < 1:
            raise ValueError("worker_number must be >= 1")
        self.worker_number = worker_number
        self._execution: HandlerExecution | None = None
        super().__init__(
            consumer_name=consumer_name,
            consumer_group=consumer_group,
            stream_name=stream_name,
            batch_size=batch_size,
            block_time=block_time,
            message_class=message_class,
            process_message_callable=process_message_callable,
            max_retry_number=max_retry_number,
            max_in_flight=worker_number,
            start_from=start_from,
            reclaim_idle_ms=reclaim_idle_ms,
            reclaim_batch_size=reclaim_batch_size,
            reclaim_poll_interval_s=reclaim_poll_interval_s,
            drain_timeout_s=drain_timeout_s,
            stream_maxlen=stream_maxlen,
            dlq_maxlen=dlq_maxlen,
            close_redis_on_stop=close_redis_on_stop,
            current_redis_manager=current_redis_manager,
            max_processing_time_s=max_processing_time_s,
            step_progress_timeout_s=step_progress_timeout_s,
            use_execution_lease=use_execution_lease,
            lease_ttl_ms=lease_ttl_ms,
        )

    @property
    def execution(self) -> HandlerExecution:
        if self._execution is None:
            self._execution = HandlerExecution(
                workers=self.worker_number, batch_size=self.batch_size
            )
        return self._execution

    @execution.setter
    def execution(self, value: HandlerExecution) -> None:
        self._execution = value

    @property
    def executor(self) -> ThreadPoolExecutor | None:
        return self._execution.executor if self._execution is not None else None

    @executor.setter
    def executor(self, value: ThreadPoolExecutor | None) -> None:
        if value is None:
            if self._execution is not None:
                self._execution.close()
                self._execution = None
        else:
            self.execution.executor = value

    def _ensure_executor(self) -> ThreadPoolExecutor:
        return self.execution.executor

    async def _shutdown_executor(self) -> None:
        if self._execution is not None:
            self._execution.close()
            self._execution = None

    def _prepare_execution_resources(self) -> None:
        self._ensure_executor()

    async def _release_execution_resources(self) -> None:
        await self._shutdown_executor()

    def _submit_message(
        self,
        loop: asyncio.AbstractEventLoop,
        message_data: T,
        retry_count: int,
        tracker: ProgressTracker | None = None,
    ) -> asyncio.Future[Any]:
        func = functools.partial(
            self._process_message_sync_wrapper, message_data, retry_count, tracker
        )
        return loop.run_in_executor(self.executor, func)

    def _process_message_sync_wrapper(
        self,
        message: T,
        retry_count: int,
        tracker: ProgressTracker | None = None,
    ) -> None:
        """Fonction exécutée dans un thread avec un runner asyncio dédié."""

        async def _coro_runner() -> None:
            token = current_progress_tracker.set(tracker)
            try:
                await self.process_message_callable(
                    message, retry_count, retry_count >= self.max_retry_number - 1
                )
            finally:
                current_progress_tracker.reset(token)

        run_handler_in_thread(_coro_runner)
