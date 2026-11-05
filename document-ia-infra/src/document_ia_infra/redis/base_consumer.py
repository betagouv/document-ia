"""
Classe abstraite BaseConsumer pour les consommateurs Redis Stream.
"""

import asyncio
import contextlib
import json
import logging
import os
import secrets
import socket
import time
from abc import ABC, abstractmethod
from asyncio import Task
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar, cast
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError
from redis.typing import EncodableT, FieldT

from document_ia_infra.redis.progress_tracker import ProgressTracker
from document_ia_infra.redis.redis_manager import (
    RedisManager,
)
from document_ia_infra.redis.redis_manager import (
    redis_manager as redis_manager_main_thread,
)
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_infra.redis.serializable_message import SerializableMessage
from document_ia_infra.redis.stream_delivery import StreamDelivery
from document_ia_infra.redis.worker_error_policy import WorkerErrorPolicy

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SerializableMessage)

RECLAIM_IDLE_MS = 300000
DLQ_SCAN_BATCH_SIZE = 200
RESOURCE_CLOSE_TIMEOUT_S = 5.0
_PROCESS_BOOT_ID = secrets.token_hex(4)

__all__ = [
    "BaseConsumer",
    "DLQ_SCAN_BATCH_SIZE",
    "InFlightContext",
    "RECLAIM_IDLE_MS",
    "build_instance_consumer_name",
]


@dataclass
class InFlightContext:
    msg_id: str
    fields: dict[str, Any]
    tracker: ProgressTracker
    future: asyncio.Future[Any] | None = None
    execution_id: str | None = None
    lease_token: str | None = None
    handled: bool = False


def build_instance_consumer_name(base_name: str) -> str:
    """Nom de consommateur unique par instance et par démarrage de processus.

    En mode groupé, chaque instance doit posséder une identité de consommateur
    distincte et observable (XINFO CONSUMERS) : les entrées livrées mais non
    acquittées restent dans la PEL du consommateur qui les a lues, et la
    récupération par XAUTOCLAIM suppose de pouvoir distinguer les instances,
    y compris après redémarrage d'un conteneur avec PID 1.
    """
    raw_host = socket.gethostname().strip() or "unknown"
    safe_host = "-".join(raw_host.split())
    return f"{base_name}-{safe_host}-{os.getpid()}-{_PROCESS_BOOT_ID}"


class BaseConsumer(ABC, Generic[T]):
    """Socle commun des consommateurs Redis Stream avec groupe, retry, DLQ et récupération PEL.

    Toute la logique Redis (lecture ``XREADGROUP``, battement de cœur ``XCLAIM JUSTID``,
    récupération ``XAUTOCLAIM``, remise en file, DLQ idempotente et arrêt gracieux)
    est mutualisée ici. Les sous-classes spécialisent uniquement le mode d'exécution :
    - :class:`ThreadConsumer` : pool de threads avec boucle ``asyncio`` dédiée par thread
      (adapté aux traitements CPU-bound du worker).
    - :class:`AsyncIoConsumer` : tâches ``asyncio`` natives sur la boucle courante
      (adapté aux traitements I/O-bound de l'API partageant les pools existants).
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
        max_in_flight: int,
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
        if max_retry_number < 1:
            raise ValueError("max_retry_number must be >= 1")
        if max_in_flight < 1:
            raise ValueError("max_in_flight must be >= 1")
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if reclaim_idle_ms is not None and reclaim_idle_ms < 0:
            raise ValueError("reclaim_idle_ms must be >= 0")
        if drain_timeout_s < 0:
            raise ValueError("drain_timeout_s must be >= 0")
        if max_processing_time_s is not None and max_processing_time_s <= 0:
            raise ValueError("max_processing_time_s must be > 0")
        if step_progress_timeout_s is not None and step_progress_timeout_s <= 0:
            raise ValueError("step_progress_timeout_s must be > 0")
        if lease_ttl_ms is not None and lease_ttl_ms <= 0:
            raise ValueError("lease_ttl_ms must be > 0")

        self.redis: Redis | None = None
        self._custom_redis_manager = current_redis_manager
        self.listener_task: Task[Any] | None = None
        self.reclaimer_task: Task[Any] | None = None
        self.heartbeat_task: Task[Any] | None = None
        self.stop_flag = asyncio.Event()

        self.consumer_name = consumer_name
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.message_class = message_class
        self.process_message_callable = process_message_callable

        self.batch_size = batch_size
        self.block_time = block_time  # en ms pour xreadgroup
        self.max_in_flight = max_in_flight
        self.max_retry_number = max_retry_number
        self.start_from = start_from
        self._reclaim_idle_ms_override = reclaim_idle_ms
        self.reclaim_batch_size = (
            reclaim_batch_size if reclaim_batch_size is not None else batch_size
        )
        self.reclaim_poll_interval_s = reclaim_poll_interval_s
        self.drain_timeout_s = drain_timeout_s
        self.stream_maxlen = stream_maxlen
        self.dlq_maxlen = dlq_maxlen
        self.close_redis_on_stop = close_redis_on_stop

        self.max_processing_time_s = max_processing_time_s
        self.step_progress_timeout_s = step_progress_timeout_s
        self.use_execution_lease = use_execution_lease
        self.lease_ttl_ms = (
            lease_ttl_ms
            if lease_ttl_ms is not None
            else int(redis_settings.DEFAULT_LEASE_TTL_MS)
        )

        self.dlq_stream_name = f"{self.stream_name}:dlq"

        self.delivery = StreamDelivery(stream_name, consumer_group, consumer_name)
        self.error_policy = WorkerErrorPolicy(max_retry_number)

        self._in_flight_ids: set[str] = set()
        self._reclaiming_ids: set[str] = set()
        self._processing_futures: set[asyncio.Future[Any]] = set()
        self._in_flight_contexts: dict[str, InFlightContext] = {}
        self._listener_active = False
        self._reclaimer_active = False
        self._needs_group_init = False
        self._listener_done = asyncio.Event()
        self._draining = False
        self._heartbeat_interval_s_override: float | None = None

    @property
    def has_running_handlers(self) -> bool:
        """Indique si des traitements de messages sont actuellement en cours d'exécution."""
        return any(not future.done() for future in self._processing_futures)

    @property
    def _redis_manager(self) -> RedisManager:
        return self._custom_redis_manager or redis_manager_main_thread

    @property
    def reclaim_idle_ms(self) -> int:
        if self._reclaim_idle_ms_override is not None:
            return self._reclaim_idle_ms_override
        import sys

        base_mod = sys.modules.get("document_ia_infra.redis.base_consumer")
        if (
            base_mod is not None
            and getattr(base_mod, "RECLAIM_IDLE_MS", None) != 300000
        ):
            return int(getattr(base_mod, "RECLAIM_IDLE_MS"))
        consumer_mod = sys.modules.get("document_ia_infra.redis.consumer")
        if (
            consumer_mod is not None
            and getattr(consumer_mod, "RECLAIM_IDLE_MS", None) != 300000
        ):
            return int(getattr(consumer_mod, "RECLAIM_IDLE_MS"))
        return RECLAIM_IDLE_MS

    @property
    def _heartbeat_interval_s(self) -> float:
        if self._heartbeat_interval_s_override is not None:
            return self._heartbeat_interval_s_override
        return max(self.reclaim_idle_ms / 3, 10) / 1000.0

    @_heartbeat_interval_s.setter
    def _heartbeat_interval_s(self, value: float) -> None:
        self._heartbeat_interval_s_override = value

    def is_healthy(self) -> bool:
        """Indique si les trois tâches de fond du consommateur sont actives."""
        if self.stop_flag.is_set():
            return False
        tasks = (self.listener_task, self.reclaimer_task, self.heartbeat_task)
        return all(t is not None and not t.done() for t in tasks)

    def _prepare_execution_resources(self) -> None:
        """Hook d'initialisation des ressources propres au mode d'exécution."""

    async def _release_execution_resources(self) -> None:
        """Hook de libération des ressources propres au mode d'exécution."""

    async def _abort_unfinished_futures(
        self, unfinished: list[asyncio.Future[Any]]
    ) -> None:
        """Hook appelé en sortie de boucle sur les futures non terminées après vidange."""
        if self.use_execution_lease and self.redis is not None:
            for ctx in list(self._in_flight_contexts.values()):
                if ctx.execution_id and ctx.lease_token and not ctx.handled:
                    with contextlib.suppress(Exception):
                        await self.delivery.release_lease(
                            self.redis, ctx.execution_id, ctx.lease_token
                        )

    @abstractmethod
    def _submit_message(
        self,
        loop: asyncio.AbstractEventLoop,
        message_data: T,
        retry_count: int,
        tracker: ProgressTracker | None = None,
    ) -> asyncio.Future[Any]:
        """Soumet le traitement d'un message selon la stratégie de la sous-classe."""

    async def start(self) -> None:
        """Démarre le consommateur en tâche de fond (cycle de vie non bloquant)."""
        if self.is_healthy():
            return
        if any(
            t is not None and not t.done()
            for t in (self.listener_task, self.reclaimer_task, self.heartbeat_task)
        ):
            await self._stop_tasks_only()

        self.stop_flag.clear()
        self._listener_done.clear()
        self._prepare_execution_resources()

        redis_conn = await self._ensure_connection()
        if redis_conn is not None:
            try:
                await self._ensure_consumer_group(redis_conn)
                self._needs_group_init = False
            except Exception as group_err:
                logger.warning(
                    "Initial consumer group setup failed for '%s': %s; will retry in background",
                    self.stream_name,
                    group_err,
                )
                self._needs_group_init = True
        else:
            self._needs_group_init = True

        self.listener_task = asyncio.create_task(
            self._start_listening_messages(),
            name=f"consumer-listener:{self.stream_name}",
        )
        self.reclaimer_task = asyncio.create_task(
            self._reclaim_pending_messages(),
            name=f"consumer-reclaimer:{self.stream_name}",
        )
        self.heartbeat_task = asyncio.create_task(
            self._heartbeat_in_flight_entries(),
            name=f"consumer-heartbeat:{self.stream_name}",
        )
        logger.info(
            "%s started in background (stream='%s', group='%s', consumer='%s', max_in_flight=%d)",
            type(self).__name__,
            self.stream_name,
            self.consumer_group,
            self.consumer_name,
            self.max_in_flight,
        )

    async def _stop_tasks_only(self) -> None:
        self.stop_flag.set()
        stop_wait_timeout = (self.block_time / 1000.0) + self.drain_timeout_s + 5.0

        worker_tasks = [
            t
            for t in (self.listener_task, self.reclaimer_task)
            if t is not None and not t.done()
        ]
        if worker_tasks:
            _, still_running = await asyncio.wait(
                worker_tasks, timeout=stop_wait_timeout
            )
            for task in still_running:
                logger.warning(
                    "Timeout waiting for consumer task '%s' to stop; cancelling",
                    task.get_name(),
                )
                task.cancel()
            if still_running:
                await asyncio.gather(*still_running, return_exceptions=True)
            for task in worker_tasks:
                if not task.cancelled():
                    exc = task.exception()
                    if exc is not None:
                        logger.error(
                            "Error stopping consumer task '%s': %s",
                            task.get_name(),
                            exc,
                        )

        if self._draining:
            for _ in range(3):
                try:
                    await asyncio.wait_for(
                        self._listener_done.wait(),
                        timeout=self.drain_timeout_s + 5.0,
                    )
                    break
                except (TimeoutError, asyncio.CancelledError):
                    break

        if self.heartbeat_task is not None and not self.heartbeat_task.done():
            heartbeat_cancelled: asyncio.CancelledError | None = None
            try:
                await asyncio.wait_for(self.heartbeat_task, timeout=5.0)
            except TimeoutError:
                logger.warning(
                    "Timeout waiting for consumer heartbeat task to stop; cancelling"
                )
                self.heartbeat_task.cancel()
                await asyncio.gather(self.heartbeat_task, return_exceptions=True)
            except asyncio.CancelledError as cancel_err:
                self.heartbeat_task.cancel()
                await asyncio.gather(self.heartbeat_task, return_exceptions=True)
                heartbeat_cancelled = cancel_err
            except Exception as hb_err:
                logger.error("Error stopping heartbeat task: %s", hb_err)
            if heartbeat_cancelled is not None:
                raise heartbeat_cancelled

        self.listener_task = None
        self.reclaimer_task = None
        self.heartbeat_task = None

    async def stop(self) -> None:
        """Arrête proprement les tâches de fond en maintenant le battement pendant la vidange."""
        await self._stop_tasks_only()
        await self._release_execution_resources()
        if self.close_redis_on_stop and self._custom_redis_manager is None:
            self.redis = None
            try:
                await asyncio.wait_for(
                    self._redis_manager.close(), timeout=RESOURCE_CLOSE_TIMEOUT_S
                )
            except TimeoutError:
                logger.warning("Timed out closing Redis resources during shutdown")
            except Exception as exc:
                logger.warning(
                    "Failed to close Redis resources during shutdown: %s", exc
                )

    async def start_consumer(self) -> None:
        """Démarre le consommateur en mode bloquant (utilisé par le worker)."""
        logger.info(
            "Start %s %s (max_in_flight=%d)",
            type(self).__name__,
            self.consumer_name,
            self.max_in_flight,
        )
        logger.debug("Establishing connection to Redis...")

        try:
            await self._init_consumer()
            self._listener_done.clear()
            self.heartbeat_task = asyncio.create_task(
                self._heartbeat_in_flight_entries(),
                name=f"heartbeat-{self.consumer_name}",
            )
            async with asyncio.TaskGroup() as tg:
                self.reclaimer_task = tg.create_task(
                    self._reclaim_pending_messages(),
                    name=f"reclaimer-{self.consumer_name}",
                )
                self.listener_task = tg.create_task(
                    self._start_listening_messages(),
                    name=f"listener-{self.consumer_name}",
                )
        finally:
            self.stop_flag.set()

            async def _cleanup() -> None:
                if self.listener_task is not None:
                    for _ in range(3):
                        try:
                            await asyncio.wait_for(
                                self._listener_done.wait(),
                                timeout=self.drain_timeout_s + 5.0,
                            )
                            break
                        except (TimeoutError, asyncio.CancelledError):
                            break

                if self.heartbeat_task is not None and not self.heartbeat_task.done():
                    try:
                        await asyncio.wait_for(self.heartbeat_task, timeout=5.0)
                    except (TimeoutError, asyncio.CancelledError):
                        self.heartbeat_task.cancel()
                        await asyncio.gather(
                            self.heartbeat_task, return_exceptions=True
                        )
                    except Exception:
                        pass
                await self._de_init_consumer()

            await asyncio.shield(_cleanup())

    async def _init_consumer(self) -> None:
        try:
            self._prepare_execution_resources()
            self.redis = await self._get_safe_redis_connection()
            await self._ensure_consumer_group(self.redis)
            self._needs_group_init = False
            logger.info("Consumer %s initialized and ready", self.consumer_name)
        except ConnectionError as e:
            logger.error("Error initializing consumer %s: %s", self.consumer_name, e)
            raise ConnectionError(
                "Failed to initialize consumer due to Redis connection issues"
            ) from e

    async def _de_init_consumer(self) -> None:
        logger.info("Consumer %s stopping...", self.consumer_name)
        await self._release_execution_resources()
        if self.close_redis_on_stop and self._custom_redis_manager is None:
            self.redis = None
            try:
                await asyncio.wait_for(
                    self._redis_manager.close(), timeout=RESOURCE_CLOSE_TIMEOUT_S
                )
            except TimeoutError:
                logger.warning("Timed out closing Redis resources during shutdown")
            except Exception as exc:
                logger.warning(
                    "Failed to close Redis resources during shutdown: %s", exc
                )

    async def _ensure_connection(self) -> Redis | None:
        if self.redis is not None:
            return self.redis
        self.redis = await self._redis_manager.get_connection()
        if self.redis is None:
            logger.error(
                "Consumer %s: no Redis connection available", self.consumer_name
            )
        return self.redis

    def _invalidate_connection_on_transport_error(self, exc: BaseException) -> None:
        if isinstance(
            exc,
            (
                ConnectionError,
                TimeoutError,
                OSError,
                RedisConnectionError,
                RedisTimeoutError,
            ),
        ):
            self.redis = None

    async def _sleep_unless_stopped(self, delay_s: float) -> None:
        if delay_s <= 0 or self.stop_flag.is_set():
            return
        try:
            await asyncio.wait_for(self.stop_flag.wait(), timeout=delay_s)
        except TimeoutError:
            pass

    async def _xadd_capped(
        self,
        redis_connection: Redis,
        stream_name: str,
        fields: dict[FieldT, EncodableT],
        maxlen: int | None,
    ) -> Any:
        if maxlen is not None:
            return await redis_connection.xadd(
                stream_name, fields, maxlen=maxlen, approximate=True
            )
        return await redis_connection.xadd(stream_name, fields)

    async def _start_listening_messages(self) -> None:
        active_futures: dict[asyncio.Future[Any], tuple[str, dict[str, Any]]] = {}
        self._listener_active = True

        try:
            loop = asyncio.get_running_loop()

            while not self.stop_flag.is_set():
                redis_conn = await self._ensure_connection()
                if redis_conn is None:
                    await self._sleep_unless_stopped(2.0)
                    continue
                if self._needs_group_init:
                    try:
                        await self._ensure_consumer_group(redis_conn)
                        self._needs_group_init = False
                    except Exception as group_err:
                        self._invalidate_connection_on_transport_error(group_err)
                        logger.error(
                            "Failed to initialize group '%s' on '%s': %s",
                            self.consumer_group,
                            self.stream_name,
                            group_err,
                        )
                        await self._sleep_unless_stopped(2.0)
                        continue

                # 1. Nettoyage des tâches terminées (ACK/DLQ)
                done_futures = [f for f in active_futures if f.done()]

                for fut in done_futures:
                    msg_id, fields = active_futures.pop(fut)
                    self._processing_futures.discard(fut)
                    ctx = self._in_flight_contexts.pop(msg_id, None)
                    if ctx is not None and ctx.handled:
                        self._in_flight_ids.discard(msg_id)
                        continue
                    try:
                        await self._handle_finished_future(
                            fut, msg_id, fields, redis_conn
                        )
                    finally:
                        if (
                            self.use_execution_lease
                            and ctx is not None
                            and ctx.execution_id
                            and ctx.lease_token
                        ):
                            with contextlib.suppress(Exception):
                                await self.delivery.release_lease(
                                    redis_conn, ctx.execution_id, ctx.lease_token
                                )
                        self._in_flight_ids.discard(msg_id)

                # 2. Calcul de la capacité restante
                running_count = len(active_futures)
                free_slots = self.max_in_flight - running_count

                # 3. Stratégie de lecture
                if free_slots <= 0:
                    if active_futures:
                        stop_wait = asyncio.create_task(self.stop_flag.wait())
                        _, pending = await asyncio.wait(
                            {*active_futures.keys(), stop_wait},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if stop_wait in pending:
                            stop_wait.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await stop_wait
                    continue

                current_block_time = (
                    min(200, self.block_time) if running_count > 0 else self.block_time
                )
                read_count = min(self.batch_size, free_slots)

                try:
                    response = await self.delivery.read(
                        redis_conn,
                        count=read_count,
                        block=current_block_time,
                    )
                except ResponseError as e:
                    if "NOGROUP" in str(e):
                        logger.warning(
                            "Consumer group '%s' missing on stream '%s'; recreating",
                            self.consumer_group,
                            self.stream_name,
                        )
                        try:
                            await self._ensure_consumer_group(redis_conn)
                        except Exception as recreate_err:
                            self._invalidate_connection_on_transport_error(recreate_err)
                            self._needs_group_init = True
                            logger.error(
                                "Failed to recreate consumer group '%s': %s",
                                self.consumer_group,
                                recreate_err,
                            )
                            await self._sleep_unless_stopped(1.0)
                    else:
                        logger.error(
                            "Error reading stream '%s': %s", self.stream_name, e
                        )
                        await self._sleep_unless_stopped(1.0)
                    continue
                except Exception as e:
                    self._invalidate_connection_on_transport_error(e)
                    logger.error("Error reading stream '%s': %s", self.stream_name, e)
                    await self._sleep_unless_stopped(1.0)
                    continue

                if not response:
                    continue

                _, entries = response[0]
                if not entries:
                    continue

                # Enregistrer toutes les entrées du lot avant le premier await
                # afin que le battement les protège dès leur réception.
                for raw_id, _ in entries:
                    self._in_flight_ids.add(str(raw_id))

                # 4. Soumission des nouveaux messages
                for raw_id, fields in entries:
                    msg_id = str(raw_id)
                    raw_data = fields.get("data")

                    try:
                        retry_count = self._parse_retry_count(fields)
                        if not isinstance(raw_data, str):
                            raise ValueError("Missing or non-string 'data' field")
                        message_data: T = cast(
                            T, self.message_class.from_json(raw_data)
                        )
                    except Exception as decode_err:
                        logger.error(
                            "Message decode failed: %s",
                            type(decode_err).__name__,
                        )
                        try:
                            if await self._send_to_dlq(
                                redis_connection=redis_conn,
                                msg_id=msg_id,
                                fields=fields,
                                reason="decode_error",
                                error=type(decode_err).__name__,
                            ):
                                try:
                                    await self.delivery.ack(redis_conn, msg_id)
                                except Exception:
                                    logger.error(
                                        "ACK failed for decode_error %s", msg_id
                                    )
                        finally:
                            self._in_flight_ids.discard(msg_id)
                        continue

                    execution_id: str | None = None
                    lease_token: str | None = None
                    if self.use_execution_lease:
                        execution_id = (
                            self._extract_execution_id(message_data, fields) or msg_id
                        )
                        lease_token = f"{self.consumer_name}:{uuid4()}"
                        try:
                            acquired = await self.delivery.acquire_lease(
                                redis_conn,
                                execution_id,
                                lease_token,
                                self.lease_ttl_ms,
                            )
                        except Exception as lease_err:
                            self._invalidate_connection_on_transport_error(lease_err)
                            logger.warning(
                                "Failed to acquire lease for %s: %s; deferring",
                                execution_id,
                                lease_err,
                            )
                            self._in_flight_ids.discard(msg_id)
                            continue

                        if not acquired:
                            logger.info(
                                "Execution lease for %s already held by another worker; skipping concurrent execution",
                                execution_id,
                            )
                            self._in_flight_ids.discard(msg_id)
                            continue

                    tracker = ProgressTracker(
                        msg_id=msg_id,
                        max_processing_time_s=self.max_processing_time_s,
                        step_progress_timeout_s=self.step_progress_timeout_s,
                        execution_id=execution_id,
                        lease_token=lease_token,
                    )
                    ctx = InFlightContext(
                        msg_id=msg_id,
                        fields=fields,
                        tracker=tracker,
                        execution_id=execution_id,
                        lease_token=lease_token,
                    )
                    self._in_flight_contexts[msg_id] = ctx

                    try:
                        try:
                            fut = self._submit_message(
                                loop, message_data, retry_count, tracker
                            )
                        except TypeError:
                            fut = self._submit_message(loop, message_data, retry_count)
                        ctx.future = fut
                        active_futures[fut] = (msg_id, fields)
                        self._processing_futures.add(fut)
                    except Exception as submit_err:
                        logger.error(
                            "Failed to submit message %s for processing: %s",
                            msg_id,
                            submit_err,
                        )
                        self._in_flight_ids.discard(msg_id)
                        self._in_flight_contexts.pop(msg_id, None)
                        if self.use_execution_lease and execution_id and lease_token:
                            with contextlib.suppress(Exception):
                                await self.delivery.release_lease(
                                    redis_conn, execution_id, lease_token
                                )

        except asyncio.CancelledError:
            self.stop_flag.set()
            raise
        except Exception as e:
            logger.error("Error in consumer loop shutdown: %s", type(e).__name__)
            self.stop_flag.set()
            raise
        finally:
            drain_cancelled: asyncio.CancelledError | None = None
            try:
                if active_futures and self.drain_timeout_s > 0:
                    logger.info(
                        "Waiting for %d in-flight task(s) to finish...",
                        len(active_futures),
                    )
                    try:
                        await asyncio.wait(
                            active_futures.keys(), timeout=self.drain_timeout_s
                        )
                    except asyncio.CancelledError as cancel_err:
                        drain_cancelled = cancel_err
                # Traiter systématiquement toutes les futures déjà terminées (même après annulation)
                done_at_exit = [f for f in list(active_futures) if f.done()]
                if done_at_exit:
                    redis_conn = self.redis or await self._ensure_connection()
                    if redis_conn is not None:
                        await asyncio.shield(
                            self._finalize_done_futures(
                                done_at_exit, active_futures, redis_conn
                            )
                        )
                if drain_cancelled is not None:
                    raise drain_cancelled
            finally:
                try:
                    if active_futures:
                        unfinished = [f for f in active_futures if not f.done()]
                        if unfinished:
                            await self._abort_unfinished_futures(unfinished)
                finally:
                    pending = {f for f in active_futures if not f.done()}
                    if pending:
                        pending_ids = {
                            active_futures[f][0] for f in pending if f in active_futures
                        }
                        asyncio.create_task(
                            self._drain_pending(pending, pending_ids, active_futures)
                        )
                        self._draining = True
                    else:
                        self._listener_done.set()
                        self._in_flight_ids.clear()
                        self._processing_futures.clear()
                    self._listener_active = False

    async def _drain_pending(
        self,
        pending: set[asyncio.Future[Any]],
        pending_ids: set[str],
        active_futures: dict[asyncio.Future[Any], tuple[str, dict[str, Any]]],
    ) -> None:
        """Achève les handlers restants puis lève la protection du battement."""
        try:
            if pending:
                await asyncio.wait(pending)
        except Exception:
            pass
        finally:
            try:
                done = [f for f in pending if f.done()]
                if done:
                    redis_conn = self.redis or await self._ensure_connection()
                    if redis_conn is not None:
                        await asyncio.shield(
                            self._finalize_done_futures(
                                done, active_futures, redis_conn
                            )
                        )
            except Exception as e:
                logger.error("Error finalizing drained futures: %s", e)
            finally:
                self._in_flight_ids.difference_update(pending_ids)
                self._processing_futures.difference_update(pending)
                self._draining = False
                self._listener_done.set()

    async def _finalize_done_futures(
        self,
        done_futures: list[asyncio.Future[Any]],
        active_futures: dict[asyncio.Future[Any], tuple[str, dict[str, Any]]],
        redis_conn: Redis,
    ) -> None:
        for fut in done_futures:
            self._processing_futures.discard(fut)
            popped = active_futures.pop(fut, None)
            if popped is None:
                continue
            msg_id, fields = popped
            ctx = self._in_flight_contexts.pop(msg_id, None)
            if ctx is not None and ctx.handled:
                self._in_flight_ids.discard(msg_id)
                continue
            try:
                await self._handle_finished_future(fut, msg_id, fields, redis_conn)
            finally:
                if (
                    self.use_execution_lease
                    and ctx is not None
                    and ctx.execution_id
                    and ctx.lease_token
                ):
                    with contextlib.suppress(Exception):
                        await self.delivery.release_lease(
                            redis_conn, ctx.execution_id, ctx.lease_token
                        )
                self._in_flight_ids.discard(msg_id)

    async def _handle_finished_future(
        self,
        fut: asyncio.Future[Any],
        msg_id: str,
        fields: dict[str, Any],
        redis_connection: Redis,
    ) -> None:
        """Gestionnaire de résultat d'une tâche terminée (ACK / Requeue / DLQ)."""
        await self.error_policy.finish(
            fut,
            msg_id,
            fields,
            redis_connection,
            self.delivery,
            self._requeue_once,
            self._send_to_dlq,
        )

    async def _ensure_consumer_group(self, redis_connection: Redis) -> None:
        await self.delivery.ensure_group(redis_connection, self.start_from)
        logger.info(
            "Consumer group ready stream=%s, group=%s, start_from=%s",
            self.stream_name,
            self.consumer_group,
            self.start_from,
        )

    async def _get_safe_redis_connection(self) -> Redis:
        self.redis = await self._redis_manager.get_connection()
        if self.redis is None:
            logger.error("No Redis connection available, cannot start consumer")
            raise ConnectionError("No Redis connection available")
        return self.redis

    @staticmethod
    def _parse_retry_count(fields: dict[str, Any]) -> int:
        if "retries" not in fields:
            return 0
        raw_retries = fields["retries"]
        if isinstance(raw_retries, bool) or raw_retries is None:
            raise ValueError(f"Invalid retries value: {raw_retries!r}")
        retry_count = int(raw_retries)
        if retry_count < 0:
            raise ValueError(f"Negative retries value: {retry_count}")
        return retry_count

    @staticmethod
    def _resolve_root_id(fields: dict[str, Any], msg_id: str) -> str:
        raw_root = fields.get("root_id") or fields.get("original_id")
        if raw_root:
            return str(raw_root)
        return str(msg_id)

    @staticmethod
    def _extract_execution_id(message_data: Any, fields: dict[str, Any]) -> str | None:
        if hasattr(message_data, "workflow_execution_id"):
            val = getattr(message_data, "workflow_execution_id")
            if val:
                return str(val)
        if hasattr(message_data, "execution_id"):
            val = getattr(message_data, "execution_id")
            if val:
                return str(val)
        raw_data = fields.get("data")
        if isinstance(raw_data, str) and "workflow_execution_id" in raw_data:
            try:
                parsed = json.loads(raw_data)
                if isinstance(parsed, dict) and "workflow_execution_id" in parsed:
                    return str(parsed["workflow_execution_id"])
            except Exception:
                pass
        return None

    @classmethod
    def _build_requeue_fields(
        cls, fields: dict[str, Any], original_id: str, attempts: int
    ) -> dict[str, Any]:
        requeued: dict[str, Any] = {}
        for key, value in fields.items():
            if value is not None:
                requeued[str(key)] = str(value)
        requeued["retries"] = str(attempts)
        requeued["original_id"] = str(original_id)
        requeued["root_id"] = cls._resolve_root_id(fields, original_id)
        if "timestamp" in fields and "original_timestamp" not in requeued:
            requeued["original_timestamp"] = str(fields["timestamp"])
        return requeued

    @staticmethod
    def _dlq_scan_start_id(msg_id: str) -> str:
        source_ms, sep, _seq = msg_id.partition("-")
        if sep and source_ms.isdigit():
            return f"{source_ms}-0"
        return "-"

    @staticmethod
    def _stream_scan_after_id(msg_id: str) -> str:
        ms, sep, seq = msg_id.partition("-")
        if sep and ms.isdigit() and seq.isdigit():
            return f"({msg_id}"
        return "-"

    async def _already_retained_in_dlq(
        self, redis_connection: Redis, msg_id: str
    ) -> bool:
        """Vérifie si le message d'origine est déjà conservé dans la DLQ.

        Lève toute erreur Redis afin que les appelants échouent en mode fermé
        (pas d'écriture DLQ en doublon ni d'ACK prématuré si la lecture échoue).
        """
        cursor = self._dlq_scan_start_id(msg_id)
        target_id = str(msg_id)
        while True:
            entries = await redis_connection.xrange(
                self.dlq_stream_name, min=cursor, count=DLQ_SCAN_BATCH_SIZE
            )
            for _entry_id, entry_fields in entries:
                if str(entry_fields.get("original_id", "")) == target_id:
                    return True
            if len(entries) < DLQ_SCAN_BATCH_SIZE:
                return False
            cursor = f"({entries[-1][0]}"

    async def _already_requeued(self, redis_connection: Redis, msg_id: str) -> bool:
        """Vérifie lors d'un reclaim si l'entrée a déjà été copiée avant un échec d'ACK.

        Échec fermé : toute erreur Redis remonte à l'appelant pour laisser
        l'entrée en attente sans créer de doublon.
        """
        target_id = str(msg_id)
        cursor = self._stream_scan_after_id(target_id)
        while True:
            entries = await redis_connection.xrange(
                self.stream_name, min=cursor, count=DLQ_SCAN_BATCH_SIZE
            )
            for _entry_id, entry_fields in entries:
                if str(entry_fields.get("original_id", "")) == target_id:
                    return True
            if len(entries) < DLQ_SCAN_BATCH_SIZE:
                return False
            cursor = f"({entries[-1][0]}"

    async def _send_to_dlq(
        self,
        redis_connection: Redis,
        msg_id: str,
        fields: dict[str, Any],
        reason: str,
        error: str | None = None,
        *,
        skip_retention_check: bool = False,
    ) -> bool:
        """Conserve le message dans le flux DLQ de façon atomique et idempotente via Lua."""
        if not skip_retention_check:
            try:
                if await self._already_retained_in_dlq(redis_connection, msg_id):
                    logger.info(
                        "Message %s already retained in DLQ stream '%s'; skipping duplicate write",
                        msg_id,
                        self.dlq_stream_name,
                    )
                    return True
            except Exception as scan_err:
                logger.error(
                    "Failed to scan DLQ stream '%s' for %s: %s",
                    self.dlq_stream_name,
                    msg_id,
                    type(scan_err).__name__,
                )
                return False

        dlq_fields: dict[str, Any] = {
            "data": str(fields.get("data", "")),
            "retries": str(fields.get("retries", "0")),
            "original_id": str(msg_id),
            "root_id": self._resolve_root_id(fields, msg_id),
            "reason": reason,
            "error": error or "",
            "failure_class": fields.get("failure_class", "internal"),
            "consumer": self.consumer_name,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        orig_ts = fields.get("original_timestamp") or fields.get("timestamp")
        if orig_ts is not None:
            dlq_fields["original_timestamp"] = str(orig_ts)

        try:
            retained = await self.delivery.retain(redis_connection, msg_id, dlq_fields)
            if retained:
                logger.warning(
                    "Message %s moved to DLQ '%s'",
                    msg_id,
                    self.dlq_stream_name,
                )
            return retained
        except Exception as dlq_err:
            logger.error(
                "Failed to retain message %s in DLQ '%s': %s; leaving entry pending",
                msg_id,
                self.dlq_stream_name,
                type(dlq_err).__name__,
            )
            return False

    async def _requeue_once(
        self,
        redis_connection: Redis,
        msg_id: str,
        data_or_fields: str | dict[str, Any],
        attempts: int,
    ) -> bool:
        """Remet une entrée en file de façon atomique et idempotente via Lua.

        Retourne True si l'opération a réussi (copie créée ou déjà présente) ;
        lève une exception sur erreur Redis afin que l'appelant laisse l'entrée
        en attente dans la PEL pour une prochaine tentative.
        """
        if isinstance(data_or_fields, str):
            fields: dict[str, Any] = {
                "data": data_or_fields,
            }
        else:
            fields = data_or_fields
        requeued_fields = self._build_requeue_fields(fields, msg_id, attempts)
        return await self.delivery.requeue(
            redis_connection, msg_id, requeued_fields, attempts
        )

    def _worker_tasks_done(self) -> bool:
        listener_done = self.listener_task is None or (
            self.listener_task.done()
            and not self._listener_active
            and not self._draining
            and self._listener_done.is_set()
        )
        reclaimer_done = (
            self.reclaimer_task is None or self.reclaimer_task.done()
        ) and not self._reclaimer_active
        return listener_done and reclaimer_done

    async def _heartbeat_in_flight_entries(self) -> None:
        """Rafraîchit l'inactivité des entrées saines et gère le watchdog des timeouts."""
        logger.info(
            "Heartbeat task started (stream='%s', interval=%.3fs)",
            self.stream_name,
            self._heartbeat_interval_s,
        )
        while True:
            interval_s = self._heartbeat_interval_s
            if self.stop_flag.is_set():
                if self._worker_tasks_done():
                    break
                active_tasks = [
                    t
                    for t in (self.listener_task, self.reclaimer_task)
                    if t is not None and not t.done()
                ]
                drain_wait = min(interval_s, 1.0)
                if active_tasks:
                    await asyncio.wait(active_tasks, timeout=drain_wait)
                    if self._worker_tasks_done():
                        break
                else:
                    await asyncio.sleep(min(interval_s, 0.05))
            else:
                try:
                    await asyncio.wait_for(self.stop_flag.wait(), timeout=interval_s)
                except TimeoutError:
                    pass

            redis_conn = await self._ensure_connection()
            if redis_conn is None:
                continue

            now = time.monotonic()
            healthy_ids: set[str] = set()
            timed_out_contexts: list[InFlightContext] = []

            for msg_id in list(self._in_flight_ids):
                ctx = self._in_flight_contexts.get(msg_id)
                if ctx is None:
                    # Message en cours de préparation ou reclaim; maintenir le battement
                    healthy_ids.add(msg_id)
                    continue

                if ctx.handled:
                    continue

                if ctx.tracker.is_healthy(now):
                    healthy_ids.add(msg_id)
                    if (
                        self.use_execution_lease
                        and ctx.execution_id
                        and ctx.lease_token
                    ):
                        try:
                            renewed = await self.delivery.renew_lease(
                                redis_conn,
                                ctx.execution_id,
                                ctx.lease_token,
                                self.lease_ttl_ms,
                            )
                            if not renewed:
                                logger.warning(
                                    "Execution lease lost for execution_id=%s, msg_id=%s",
                                    ctx.execution_id,
                                    msg_id,
                                )
                                ctx.tracker.abort("lease_lost")
                                healthy_ids.discard(msg_id)
                                timed_out_contexts.append(ctx)
                        except Exception as renew_err:
                            self._invalidate_connection_on_transport_error(renew_err)
                            logger.warning(
                                "Failed to renew lease for %s: %s",
                                ctx.execution_id,
                                renew_err,
                            )
                else:
                    timed_out_contexts.append(ctx)

            ids_to_refresh = healthy_ids | self._reclaiming_ids
            if ids_to_refresh:
                try:
                    await self.delivery.refresh(redis_conn, ids_to_refresh)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self._invalidate_connection_on_transport_error(e)
                    logger.warning(
                        "Heartbeat failed for stream=%s: %s",
                        self.stream_name,
                        type(e).__name__,
                    )

            for ctx in timed_out_contexts:
                if ctx.handled:
                    continue
                await self._handle_timed_out_entry(redis_conn, ctx)
        logger.info("Heartbeat task stopped (stream='%s')", self.stream_name)

    async def _handle_timed_out_entry(
        self, redis_conn: Redis, ctx: InFlightContext
    ) -> None:
        """Gère un message en timeout : arrêt heartbeat, fencing, annulation et rejeu immédiat."""
        ctx.handled = True
        msg_id = ctx.msg_id
        self._in_flight_ids.discard(msg_id)

        timeout_reason = ctx.tracker.check_timeout_reason() or "processing_timeout"
        logger.warning(
            "Watchdog detected timeout for message %s (stream='%s', reason='%s')",
            msg_id,
            self.stream_name,
            timeout_reason,
        )

        ctx.tracker.abort(timeout_reason)

        if ctx.future is not None and not ctx.future.done():
            ctx.future.cancel()

        if self.use_execution_lease and ctx.execution_id and ctx.lease_token:
            with contextlib.suppress(Exception):
                await self.delivery.release_lease(
                    redis_conn, ctx.execution_id, ctx.lease_token
                )

        try:
            retry_count = self._parse_retry_count(ctx.fields)
        except Exception:
            retry_count = 0

        attempts = retry_count + 1
        if attempts >= self.max_retry_number:
            logger.error(
                "Max attempts exceeded for timed out message %s. Moving to DLQ with reason '%s'.",
                msg_id,
                timeout_reason,
            )
            try:
                retained = await self._send_to_dlq(
                    redis_connection=redis_conn,
                    msg_id=msg_id,
                    fields=ctx.fields,
                    reason=timeout_reason,
                    error=f"Timeout: {timeout_reason} (attempts {attempts}/{self.max_retry_number})",
                )
                if retained:
                    await self.delivery.ack(redis_conn, msg_id)
            except Exception as dlq_err:
                self._invalidate_connection_on_transport_error(dlq_err)
                logger.error(
                    "Failed to retain timed out message %s in DLQ: %s",
                    msg_id,
                    dlq_err,
                )
        else:
            logger.info(
                "Immediate requeue of timed out message %s with retries=%d (reason='%s')",
                msg_id,
                attempts,
                timeout_reason,
            )
            try:
                requeued = await self._requeue_once(
                    redis_conn, msg_id, ctx.fields, attempts
                )
                if requeued:
                    await self.delivery.ack(redis_conn, msg_id)
                    logger.info("Acknowledged original timed out message %s", msg_id)
            except Exception as requeue_err:
                self._invalidate_connection_on_transport_error(requeue_err)
                logger.error(
                    "Failed to requeue timed out message %s: %s",
                    msg_id,
                    requeue_err,
                )

    async def _reclaim_pending_messages(self) -> None:
        """Récupère les messages en attente inactifs depuis plus de reclaim_idle_ms."""
        logger.info("Reclaimer task started idle_ms=%d", self.reclaim_idle_ms)
        start = "0-0"
        self._reclaimer_active = True

        try:
            while not self.stop_flag.is_set():
                try:
                    redis_conn = await self._ensure_connection()
                    if redis_conn is None:
                        await self._sleep_unless_stopped(2.0)
                        continue
                    if self._needs_group_init:
                        await self._ensure_consumer_group(redis_conn)
                        self._needs_group_init = False

                    next_start, claimed, _ = await self.delivery.claim(
                        redis_conn,
                        self.reclaim_idle_ms,
                        start,
                        count=self.reclaim_batch_size,
                    )
                    if self.stop_flag.is_set():
                        break
                    # Séparer les entrées activement en cours de traitement par ce consommateur
                    # de celles abandonnées par d'autres instances.
                    valid_claimed: list[tuple[str, dict[str, Any] | None]] = []
                    own_in_flight_ids: list[str] = []
                    for raw_id, fields in claimed:
                        mid = str(raw_id)
                        if mid in self._in_flight_ids:
                            own_in_flight_ids.append(mid)
                        else:
                            valid_claimed.append((mid, fields))

                    if own_in_flight_ids:
                        logger.info(
                            "Consumer %s reclaimed %d of its own in-flight entries; refreshing idle timer and skipping reclaim",
                            self.consumer_name,
                            len(own_in_flight_ids),
                        )
                        try:
                            await self.delivery.refresh(
                                redis_conn, set(own_in_flight_ids)
                            )
                        except Exception as claim_err:
                            logger.warning(
                                "Failed to refresh idle timer for in-flight entries: %s",
                                claim_err,
                            )

                    claimed_ids = {mid for mid, _ in valid_claimed}
                    self._reclaiming_ids.update(claimed_ids)
                    try:
                        for msg_id, fields in valid_claimed:
                            if msg_id in self._in_flight_ids:
                                continue
                            try:
                                await self._reclaim_entry(redis_conn, msg_id, fields)
                            finally:
                                self._reclaiming_ids.discard(msg_id)
                    finally:
                        self._reclaiming_ids.difference_update(claimed_ids)
                    start = str(next_start) if next_start else "0-0"
                    pause_s = (
                        min(1.0, self.reclaim_poll_interval_s)
                        if (claimed or start not in ("0-0", "0"))
                        else self.reclaim_poll_interval_s
                    )
                    await self._sleep_unless_stopped(pause_s)
                except asyncio.CancelledError:
                    break
                except ResponseError as e:
                    if "NOGROUP" in str(e):
                        redis_conn = await self._ensure_connection()
                        if redis_conn is not None:
                            try:
                                await self._ensure_consumer_group(redis_conn)
                            except Exception as recreate_err:
                                self._invalidate_connection_on_transport_error(
                                    recreate_err
                                )
                                self._needs_group_init = True
                    else:
                        logger.error(
                            "Error reclaiming pending messages: %s", type(e).__name__
                        )
                    await self._sleep_unless_stopped(5.0)
                except Exception as e:
                    self._invalidate_connection_on_transport_error(e)
                    logger.error(
                        "Error reclaiming pending messages: %s", type(e).__name__
                    )
                    await self._sleep_unless_stopped(5.0)
        finally:
            self._reclaimer_active = False
        logger.info("Reclaimer task stopped")

    async def _reclaim_entry(
        self,
        redis_or_id: Redis | str | None = None,
        msg_id_or_fields: str | dict[str, Any] | None = None,
        fields_opt: dict[str, Any] | None = None,
        *,
        redis_connection: Redis | None = None,
        msg_id: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> None:
        if redis_connection is not None or msg_id is not None:
            actual_redis = (
                redis_connection or self.redis or await self._ensure_connection()
            )
            actual_msg_id = msg_id or (
                redis_or_id if isinstance(redis_or_id, str) else None
            )
            if fields is not None:
                actual_fields = fields
            elif isinstance(msg_id_or_fields, dict):
                actual_fields = msg_id_or_fields
            else:
                actual_fields = {}
        elif isinstance(redis_or_id, str):
            actual_redis = self.redis or await self._ensure_connection()
            actual_msg_id = redis_or_id
            actual_fields = (
                msg_id_or_fields if isinstance(msg_id_or_fields, dict) else {}
            )
        else:
            actual_redis = redis_or_id
            actual_msg_id = cast(str, msg_id_or_fields)
            actual_fields = fields_opt if isinstance(fields_opt, dict) else {}

        if actual_redis is None or actual_msg_id is None:
            return

        redis_connection = actual_redis
        msg_id = actual_msg_id
        fields = actual_fields

        logger.info("Reclaimed message ID: %s", msg_id)

        if not fields or "data" not in fields or not isinstance(fields["data"], str):
            logger.error(
                "Missing 'data' field for reclaimed message %s. Moving to DLQ.",
                msg_id,
            )
            await self._retain_in_dlq_and_ack(
                redis_connection=redis_connection,
                msg_id=msg_id,
                fields=fields or {},
                reason="decode_error",
                error="Missing 'data' field in reclaimed message",
                skip_retention_check=True,
            )
            return

        try:
            retry_count = self._parse_retry_count(fields)
        except Exception:
            logger.error(
                "Malformed retries field for reclaimed message %s. Moving to DLQ.",
                msg_id,
            )
            await self._retain_in_dlq_and_ack(
                redis_connection=redis_connection,
                msg_id=msg_id,
                fields=fields,
                reason="decode_error",
                error="Malformed retries field",
                skip_retention_check=True,
            )
            return

        attempts = retry_count + 1
        if attempts >= self.max_retry_number:
            logger.error(
                "Max attempts exceeded for reclaimed message %s. Moving to DLQ.",
                msg_id,
            )
            await self._retain_in_dlq_and_ack(
                redis_connection=redis_connection,
                msg_id=msg_id,
                fields=fields,
                reason="max_retries_exceeded",
                error=f"Exceeded max retry count during reclaim ({attempts}/{self.max_retry_number})",
                skip_retention_check=True,
            )
            return

        # Pour les messages non épuisés (attempts < max_retry_number) :
        # si le message a déjà fait l'objet d'un échec terminal (decode_error,
        # not_retryable_error) et a déjà été conservé en DLQ, l'acquitter
        # sans le remettre en file.
        try:
            if await self._already_retained_in_dlq(redis_connection, msg_id):
                logger.info(
                    "Reclaimed message %s already retained in DLQ stream '%s'; skipping duplicate requeue",
                    msg_id,
                    self.dlq_stream_name,
                )
                try:
                    await self.delivery.ack(redis_connection, msg_id)
                    logger.info("Acknowledged reclaimed DLQ message %s", msg_id)
                except Exception:
                    logger.error("ACK failed for reclaimed DLQ message %s", msg_id)
                return
        except Exception as scan_err:
            logger.error(
                "Failed to scan DLQ stream '%s' for reclaimed message %s: %s; leaving entry pending",
                self.dlq_stream_name,
                msg_id,
                type(scan_err).__name__,
            )
            return

        try:
            await self._requeue_once(redis_connection, msg_id, fields, attempts)
            try:
                await self.delivery.ack(redis_connection, msg_id)
                logger.info("Acknowledged reclaimed message %s", msg_id)
            except Exception:
                logger.error("ACK failed for reclaimed %s", msg_id)
        except Exception as requeue_err:
            logger.error(
                "Failed to requeue reclaimed message %s: %s",
                msg_id,
                type(requeue_err).__name__,
            )

    async def _retain_in_dlq_and_ack(
        self,
        redis_or_id: Redis | str | None = None,
        msg_id_or_fields: str | dict[str, Any] | None = None,
        fields_or_reason: dict[str, Any] | str | None = None,
        reason_or_error: str | None = None,
        error_opt: str | None = None,
        *,
        redis_connection: Redis | None = None,
        msg_id: str | None = None,
        fields: dict[str, Any] | None = None,
        reason: str | None = None,
        error: str | None = None,
        skip_retention_check: bool = False,
    ) -> None:
        if redis_connection is not None or msg_id is not None:
            actual_redis = (
                redis_connection or self.redis or await self._ensure_connection()
            )
            actual_msg_id = msg_id or (
                redis_or_id if isinstance(redis_or_id, str) else None
            )
            if fields is not None:
                actual_fields = fields
            elif isinstance(msg_id_or_fields, dict):
                actual_fields = msg_id_or_fields
            else:
                actual_fields = {}
            actual_reason = reason or (
                fields_or_reason if isinstance(fields_or_reason, str) else "unknown"
            )
            actual_error = error or reason_or_error or error_opt or ""
        elif isinstance(redis_or_id, str):
            actual_redis = self.redis or await self._ensure_connection()
            actual_msg_id = redis_or_id
            actual_fields = cast(dict[str, Any], msg_id_or_fields)
            actual_reason = cast(str, fields_or_reason)
            actual_error = reason_or_error or ""
        else:
            actual_redis = redis_or_id
            actual_msg_id = cast(str, msg_id_or_fields)
            actual_fields = cast(dict[str, Any], fields_or_reason)
            actual_reason = cast(str, reason_or_error)
            actual_error = error_opt or ""

        if actual_redis is None or actual_msg_id is None:
            return

        retained = await self._send_to_dlq(
            redis_connection=actual_redis,
            msg_id=actual_msg_id,
            fields=actual_fields,
            reason=actual_reason,
            error=actual_error,
            skip_retention_check=skip_retention_check,
        )
        if not retained:
            logger.warning(
                "Reclaimed message %s left pending on '%s': DLQ retention unconfirmed",
                actual_msg_id,
                self.stream_name,
            )
            return
        try:
            await self.delivery.ack(actual_redis, actual_msg_id)
        except Exception:
            logger.error("ACK failed for reclaimed DLQ message %s", actual_msg_id)
