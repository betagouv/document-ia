"""
Classe Consumer commune pour les consumers Redis Stream
"""

import asyncio  # remplacement de threading+sleep
import functools
import logging
from asyncio import Task
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import TypeVar, Generic, Optional, Any, Coroutine, cast

from redis import ResponseError
from redis.asyncio import Redis
from redis.typing import FieldT, EncodableT

from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.redis.redis_manager import (
    redis_manager as redis_manager_main_thread,
)
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_infra.redis.serializable_message import SerializableMessage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SerializableMessage)

RECLAIM_IDLE_MS = 300000


class Consumer(Generic[T]):
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
    ):
        self.redis: Optional[Redis] = None
        self.reclaimer_task: Optional[Task[Any]] = None
        self.stop_flag = asyncio.Event()
        self.consumer_name = consumer_name
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.message_class = message_class
        self.process_message_callable = process_message_callable

        # Configuration du consumer
        self.batch_size = batch_size
        self.block_time = block_time  # en ms pour xreadgroup
        self.worker_number = worker_number
        self.max_retry_number = max_retry_number

        # DLQ stream
        self.dlq_stream_name = f"{self.stream_name}:dlq"

        self.executor = ThreadPoolExecutor(max_workers=self.worker_number)

    async def start_consumer(self):
        logger.info(
            f"Start consumer {self.consumer_name} with {self.worker_number} workers"
        )
        logger.debug("Establishing connection to Redis...")

        try:
            await self._init_consumer()
            async with asyncio.TaskGroup() as tg:
                self.reclaimer_task = tg.create_task(
                    self._reclaim_pending_messages(),
                    name=f"reclaimer-{self.consumer_name}",
                )
                tg.create_task(
                    self._start_listening_messages(),
                    name=f"listener-{self.consumer_name}",
                )
        except Exception as e:
            raise e
        finally:
            await self._de_init_consumer()

    async def _init_consumer(self):
        try:
            self.redis = await self._get_safe_redis_connection()
            await self._ensure_consumer_group(self.redis)
            logger.info(f"✅ Consumer {self.consumer_name} initialized and ready")
        except ConnectionError as e:
            logger.error(f"❌ Error initializing consumer {self.consumer_name}: {e}")
            raise Exception(
                "Failed to initialize consumer due to Redis connection issues"
            ) from e

    async def _de_init_consumer(self):
        logger.info(f"Consumer {self.consumer_name} stopping...")
        if self.reclaimer_task:
            try:
                await asyncio.wait_for(self.reclaimer_task, timeout=10)
            except Exception:
                pass
        self.executor.shutdown(wait=True)
        await redis_manager_main_thread.close()

    async def _start_listening_messages(self):
        self.redis = await self._get_safe_redis_connection()

        # On stocke les futures en cours EN DEHORS de la boucle while
        # Map: Future -> (msg_id, fields)
        active_futures: dict[asyncio.Future[Any], tuple[str, dict[str, Any]]] = {}

        try:
            loop = asyncio.get_running_loop()

            while not self.stop_flag.is_set():
                # 1. Nettoyage des tâches terminées (ACK/DLQ)
                # On vérifie s'il y a des tâches finies sans attendre
                # (Sauf si on est plein, voir plus bas)
                done_futures = [f for f in active_futures if f.done()]

                for fut in done_futures:
                    msg_id, fields = active_futures.pop(fut)
                    await self._handle_finished_future(fut, msg_id, fields, self.redis)

                # 2. Calcul de la capacité restante
                running_count = len(active_futures)
                free_slots = self.worker_number - running_count

                # 3. Stratégie de lecture
                if free_slots == 0:
                    # CAS A: On est PLEIN.
                    # On ne lit rien sur Redis. On attend obligatoirement qu'une tâche se finisse.
                    if active_futures:
                        _, _ = await asyncio.wait(
                            active_futures.keys(), return_when=asyncio.FIRST_COMPLETED
                        )
                    continue

                # CAS B: Il reste de la place.
                # On adapte le temps de blocage Redis.
                # Si on a des tâches en cours, on ne veut pas bloquer Redis trop longtemps
                # pour pouvoir ACK rapidement les tâches qui se terminent.
                current_block_time = 1000 if running_count > 0 else self.block_time

                try:
                    response = await self.redis.xreadgroup(
                        self.consumer_group,
                        self.consumer_name,
                        streams={self.stream_name: ">"},
                        count=free_slots,
                        block=current_block_time,
                    )
                except Exception as e:
                    logger.error(f"Error reading stream: {e}")
                    await asyncio.sleep(1)
                    continue

                if not response:
                    continue

                _, entries = response[0]
                if not entries:
                    continue

                # 4. Soumission des nouveaux messages
                for msg_id, fields in entries:
                    raw_data = fields.get("data")
                    retry_count = int(fields.get("retries", "0"))

                    try:
                        message_data: T = cast(
                            T, self.message_class.from_json(raw_data)
                        )
                    except Exception as decode_err:
                        logger.error(f"Erreur décodage message {msg_id}: {decode_err}")
                        try:
                            await self.redis.xack(
                                self.stream_name, self.consumer_group, msg_id
                            )
                        except Exception:
                            # Ne pas crash si ACK échoue
                            logger.error(f"ACK failed for decode_error {msg_id}")
                        await self._send_to_dlq(
                            redis_connection=self.redis,
                            msg_id=msg_id,
                            fields=fields,
                            reason="decode_error",
                            error=str(decode_err),
                        )
                        continue

                    func = functools.partial(
                        self._process_message_sync_wrapper, message_data, retry_count
                    )

                    fut = loop.run_in_executor(self.executor, func)
                    active_futures[fut] = (msg_id, fields)

        except Exception as e:
            logger.error(f"Error in consumer loop shutdown: {e}")
            self.stop_flag.set()
            raise e
        finally:
            # Attendre la fin des tâches restantes à l'arrêt si nécessaire
            if active_futures:
                logger.info(f"Waiting for {len(active_futures)} tasks to finish...")
                done, _ = await asyncio.wait(active_futures.keys(), timeout=10)
                # Traiter les futures terminées pour ACK/DLQ
                for fut in done:
                    msg_id, fields = active_futures.pop(fut, (None, None))  # type: ignore
                    if msg_id is not None and fields is not None:
                        await self._handle_finished_future(
                            fut, msg_id, fields, self.redis
                        )

    async def _handle_finished_future(
        self,
        fut: asyncio.Future[Any],
        msg_id: str,
        fields: dict[str, Any],
        redis_connection: Redis,
    ) -> None:
        """Gestionnaire de résultat extrait de la boucle principale pour lisibilité"""
        try:
            fut.result()
            # Succès
            try:
                await redis_connection.xack(
                    self.stream_name, self.consumer_group, msg_id
                )
            except Exception:
                # Ne pas crash si ACK échoue
                logger.error(f"ACK failed for success {msg_id}")

        except RetryableException as retry_exc:
            logger.warning(f"Retryable failure for {msg_id}: {retry_exc}")
            retry_count = int(fields.get("retries", "0"))
            data = fields.get("data", "")

            if retry_count < self.max_retry_number - 1:
                try:
                    await redis_connection.xadd(
                        self.stream_name,
                        {"data": data, "retries": str(retry_count + 1)},
                    )
                    try:
                        await redis_connection.xack(
                            self.stream_name, self.consumer_group, msg_id
                        )
                    except Exception:
                        logger.error(f"ACK failed after requeue {msg_id}")
                except Exception as requeue_err:
                    logger.error(f"Requeue failed {msg_id}: {requeue_err}")
                    await self._send_to_dlq(
                        redis_connection,
                        msg_id,
                        fields,
                        "error_requeueing_message",
                        str(requeue_err),
                    )
            else:
                logger.error(f"Max retries exceeded {msg_id}")
                await self._send_to_dlq(
                    redis_connection,
                    msg_id,
                    fields,
                    "max_retries_exceeded",
                    str(retry_exc),
                )
                try:
                    await redis_connection.xack(
                        self.stream_name, self.consumer_group, msg_id
                    )
                except Exception:
                    logger.error(f"ACK failed for max_retries_exceeded {msg_id}")

        except Exception as proc_err:
            logger.error(f"Fatal error message {msg_id}: {proc_err}")
            await self._send_to_dlq(
                redis_connection, msg_id, fields, "not_retryable_error", str(proc_err)
            )
            try:
                await redis_connection.xack(
                    self.stream_name, self.consumer_group, msg_id
                )
            except Exception:
                logger.error(f"ACK failed for not_retryable_error {msg_id}")

    def _process_message_sync_wrapper(self, message: T, retry_count: int) -> None:
        """Fonction exécutée dans un thread.
        Crée un nouvel event loop pour exécuter la coroutine process_message_callable.
        ATTENTION : si process_message_callable accède à des objets liés à l'évent loop principal
        (ex : connexion Redis asynchrone déjà créée), cela peut poser un problème. Dans ce cas, il
        faudrait refactorer pour ne déplacer dans le thread que la partie CPU-bound.
        """
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
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                logger.error("Error shutting down async generators in thread loop")
                pass
            loop.close()

    async def _ensure_consumer_group(self, redis_connection: Redis):
        try:
            await redis_connection.xgroup_create(
                name=self.stream_name,
                groupname=self.consumer_group,
                id="$",
                mkstream=True,
            )
            logger.info(
                f"Consumer group created stream = {self.stream_name}, group= {self.consumer_group}"
            )
        except ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.info(
                    f"Consumer group already exists, group = {self.consumer_group}"
                )
            else:
                raise

    async def _get_safe_redis_connection(self) -> Redis:
        self.redis = await redis_manager_main_thread.get_connection()
        if self.redis is None:
            logger.error("❌ No Redis connection available, cannot start consumer")
            raise ConnectionError("No Redis connection available")
        return self.redis

    async def _send_to_dlq(
        self,
        redis_connection: Redis,
        msg_id: str,
        fields: dict[str, Any],
        reason: str,
        error: Optional[str] = None,
    ) -> None:
        """Push a message to the Dead Letter Queue (DLQ) stream.

        Args:
            msg_id: original message id in the source stream
            fields: original message fields (from Redis XREADGROUP)
            reason: short code describing why it was sent to DLQ (e.g., 'decode_error')
            error: optional error string/details
        """
        dlq_fields: dict[FieldT, EncodableT] = {
            "data": str(fields.get("data", "")),
            "retries": str(fields.get("retries", "0")),
            "original_id": str(msg_id),
            "reason": reason,
            "error": error or "",
            "consumer": self.consumer_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            dlq_id = await redis_connection.xadd(self.dlq_stream_name, dlq_fields)
            logger.info(
                f"Pushed message {msg_id} to DLQ stream '{self.dlq_stream_name}' with id {dlq_id} (reason={reason})"
            )
        except Exception as dlq_err:
            logger.error(
                f"Failed to push message {msg_id} to DLQ after requeue failure: {dlq_err}"
            )

    # It reclaims pending messages that have been idle for more than RECLAIM_IDLE_MS
    # and re-queues them for processing
    # It uses xautoclaim to claim messages and xadd to re-queue them
    # It also increments a "retries" field in the message to track how many times it has been retried
    # If the retries exceed a certain threshold, it could be sent to a dead-letter queue (not implemented here)
    async def _reclaim_pending_messages(self):
        logger.info(f"Reclaimer task started idle_ms = {RECLAIM_IDLE_MS}")
        start = "0-0"

        self.redis = await self._get_safe_redis_connection()

        # Boucle continue jusqu'à stop_flag
        while not self.stop_flag.is_set():
            try:
                next_start, claimed, _ = await self.redis.xautoclaim(
                    self.stream_name,
                    self.consumer_group,
                    self.consumer_name,
                    RECLAIM_IDLE_MS,
                    start,
                    count=1,
                )
                for msg_id, fields in claimed:
                    logger.info(f"Reclaimed message ID: {msg_id} with fields: {fields}")
                    retry_count = int(fields.get("retries", "0")) + 1
                    if retry_count > self.max_retry_number:
                        logger.error(
                            f"Max retry count exceeded for reclaimed message {msg_id}. Moving to DLQ."
                        )
                        await self._send_to_dlq(
                            redis_connection=self.redis,
                            msg_id=msg_id,
                            fields=fields,
                            reason="max_retries_exceeded",
                            error="Exceeded max retry count during reclaim",
                        )
                        continue
                    try:
                        fields["retries"] = str(retry_count + 1)
                        await self.redis.xadd(self.stream_name, fields)
                        logger.info(f"Add new message with fields: {fields}")
                        try:
                            await self.redis.xack(
                                self.stream_name, self.consumer_group, msg_id
                            )
                            logger.info(f"Acknowledged reclaimed message {msg_id}")
                        except Exception:
                            logger.error(f"ACK failed for reclaimed {msg_id}")
                    except Exception as ack_err:
                        logger.error(
                            f"Failed to requeue reclaimed message {msg_id}: {ack_err}"
                        )
                start = next_start or "0-0"
                # Petit sleep coopératif
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error reclaiming pending messages: {e}")
                await asyncio.sleep(5)
                continue
        logger.info("Reclaimer task stopped")
