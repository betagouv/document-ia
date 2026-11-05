"""
Consommateur Redis Stream asyncio natif (AsyncIoConsumer).
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from document_ia_infra.redis.base_consumer import BaseConsumer
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
    "AsyncIoConsumer",
]


class AsyncIoConsumer(BaseConsumer[T]):
    """Consommateur Redis Stream full-asyncio (adapté aux traitements I/O-bound de l'API).

    Chaque message est planifié comme une ``asyncio.Task`` sur la boucle d'événements
    courante (compatible avec les pools SQLAlchemy et HTTP partagés du processus hôte),
    sans ``ThreadPoolExecutor`` ni paramètre ``worker_number``.

    Par défaut :
    - ``max_concurrency`` vaut ``batch_size`` pour borner le nombre de tâches en vol.
    - ``start_from`` vaut ``"0-0"`` pour ne perdre aucun événement déjà publié avant la
      création du groupe.
    - ``close_redis_on_stop`` vaut ``False`` pour préserver le gestionnaire Redis partagé.
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
        max_retry_number: int = 3,
        *,
        max_concurrency: int | None = None,
        start_from: str = "0-0",
        reclaim_idle_ms: int | None = None,
        reclaim_batch_size: int | None = None,
        reclaim_poll_interval_s: float = 1.0,
        drain_timeout_s: float = 10.0,
        stream_maxlen: int | None = redis_settings.EVENT_STREAM_MAXLEN,
        dlq_maxlen: int | None = redis_settings.DLQ_STREAM_MAXLEN,
        close_redis_on_stop: bool = False,
        current_redis_manager: RedisManager | None = None,
        max_processing_time_s: float | None = None,
        step_progress_timeout_s: float | None = None,
        use_execution_lease: bool = False,
        lease_ttl_ms: int | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if max_concurrency is not None and max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        resolved_concurrency = (
            batch_size if max_concurrency is None else max_concurrency
        )
        self.max_concurrency = resolved_concurrency
        super().__init__(
            consumer_name=consumer_name,
            consumer_group=consumer_group,
            stream_name=stream_name,
            batch_size=batch_size,
            block_time=block_time,
            message_class=message_class,
            process_message_callable=process_message_callable,
            max_retry_number=max_retry_number,
            max_in_flight=resolved_concurrency,
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

    def _submit_message(
        self,
        loop: asyncio.AbstractEventLoop,
        message_data: T,
        retry_count: int,
        tracker: ProgressTracker | None = None,
    ) -> asyncio.Future[Any]:
        del loop
        is_last_retry = retry_count >= self.max_retry_number - 1

        async def _coro_with_tracker() -> None:
            token = current_progress_tracker.set(tracker)
            try:
                await self.process_message_callable(
                    message_data, retry_count, is_last_retry
                )
            finally:
                current_progress_tracker.reset(token)

        return asyncio.create_task(_coro_with_tracker())

    async def _abort_unfinished_futures(
        self, unfinished: list[asyncio.Future[Any]]
    ) -> None:
        for fut in unfinished:
            fut.cancel()
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.gather(*unfinished, return_exceptions=True)),
                timeout=5.0,
            )
        except TimeoutError:
            logger.warning(
                "Timeout waiting for %d aborted futures to exit during shutdown",
                len(unfinished),
            )
