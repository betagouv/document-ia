"""
Consommateur Redis Stream multi-thread (ThreadConsumer).
"""

import asyncio
import functools
import gc
import logging
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

from document_ia_infra.redis.base_consumer import BaseConsumer
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
        start_from: str = "$",
        reclaim_idle_ms: int | None = None,
        reclaim_batch_size: int | None = None,
        reclaim_poll_interval_s: float = 1.0,
        drain_timeout_s: float = 10.0,
        stream_maxlen: int | None = redis_settings.EVENT_STREAM_MAXLEN,
        dlq_maxlen: int | None = redis_settings.DLQ_STREAM_MAXLEN,
        close_redis_on_stop: bool = True,
        current_redis_manager: RedisManager | None = None,
    ) -> None:
        if worker_number < 1:
            raise ValueError("worker_number must be >= 1")
        self.worker_number = worker_number
        self.executor: ThreadPoolExecutor | None = None
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
        )

    def _ensure_executor(self) -> ThreadPoolExecutor:
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=self.worker_number)
        return self.executor

    async def _shutdown_executor(self) -> None:
        executor = self.executor
        self.executor = None
        if executor is not None:
            await asyncio.to_thread(executor.shutdown, True)

    def _prepare_execution_resources(self) -> None:
        self._ensure_executor()

    async def _release_execution_resources(self) -> None:
        await self._shutdown_executor()

    def _submit_message(
        self,
        loop: asyncio.AbstractEventLoop,
        message_data: T,
        retry_count: int,
    ) -> asyncio.Future[Any]:
        executor = self._ensure_executor()
        func = functools.partial(
            self._process_message_sync_wrapper, message_data, retry_count
        )
        return loop.run_in_executor(executor, func)

    def _process_message_sync_wrapper(self, message: T, retry_count: int) -> None:
        """Fonction exécutée dans un thread avec un event loop dédié."""
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                self.process_message_callable(
                    message, retry_count, retry_count >= self.max_retry_number - 1
                )
            )
        finally:
            try:
                gc.collect()

                pending_tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
                if pending_tasks:
                    try:
                        loop.run_until_complete(
                            asyncio.wait_for(
                                asyncio.gather(*pending_tasks, return_exceptions=True),
                                timeout=5.0,
                            )
                        )
                    except TimeoutError:
                        logger.warning(
                            "Timeout waiting for pending tasks to finish during thread loop shutdown; cancelling"
                        )
                        for t in pending_tasks:
                            t.cancel()
                        loop.run_until_complete(
                            asyncio.gather(*pending_tasks, return_exceptions=True)
                        )
                    except Exception as shutdown_err:
                        logger.error(
                            "Error executing pending tasks during thread loop shutdown: %s",
                            shutdown_err,
                        )

                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception as e:
                logger.error("Error during thread loop cleanup: %s", e)
            finally:
                try:
                    loop.close()
                finally:
                    asyncio.set_event_loop(None)
