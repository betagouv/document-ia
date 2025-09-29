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

from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.redis.redis_manager import (
    redis_manager as redis_manager_main_thread,
)
from document_ia_infra.redis.serializable_message import SerializableMessage
from redis import ResponseError
from redis.asyncio import Redis
from redis.typing import FieldT, EncodableT

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SerializableMessage)

RECLAIM_IDLE_MS = 60000


class Consumer(Generic[T]):
    def __init__(
        self,
        consumer_name: str,
        consumer_group: str,
        stream_name: str,
        batch_size: int,
        block_time: int,
        message_class: type[T],
        process_message_callable: Callable[[T, int], Coroutine[Any, Any, None]],
        worker_number: int = 1,
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
        logger.info(f"Start consumer {self.consumer_name}")
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
        try:
            loop = asyncio.get_running_loop()
            # This loop continue until stop_flag is set
            # Stop flag is a signal when the process need to be shutdown
            while not self.stop_flag.is_set():
                response = await self.redis.xreadgroup(
                    self.consumer_group,
                    self.consumer_name,
                    streams={self.stream_name: ">"},
                    count=self.batch_size,
                    block=self.block_time,
                )
                if not response:
                    logger.info("No new messages, continuing...")
                    continue

                _, entries = response[0]
                if not entries:
                    continue

                # We use this barbaric definition to keep track of which future corresponds to which message
                future_map: dict[asyncio.Future[Any], tuple[str, dict[str, Any]]] = {}
                # Soumission en parallèle
                for msg_id, fields in entries:
                    raw_data = fields.get("data")
                    retry_count = int(fields.get("retries", "0"))
                    # We have to cast the data of the message to the type intended for the consumer
                    try:
                        message_data: T = cast(
                            T, self.message_class.from_json(raw_data)
                        )
                    # If we have an exception during the decoding of the data, we put the message in the DLQ because we will not be able to process it
                    except Exception as decode_err:
                        logger.error(f"Erreur décodage message {msg_id}: {decode_err}")
                        # We acknowledge the message to remove it from the stream
                        await self.redis.xack(
                            self.stream_name, self.consumer_group, msg_id
                        )
                        # Send to DLQ
                        await self._send_to_dlq(
                            redis_connection=self.redis,
                            msg_id=msg_id,
                            fields=fields,
                            reason="decode_error",
                            error=str(decode_err),
                        )
                        continue

                    # We start the processing in a thread managed by a ThreadPoolExecutor
                    func = functools.partial(
                        self._process_message_sync_wrapper, message_data, retry_count
                    )
                    # noinspection PyTypeChecker
                    fut = loop.run_in_executor(self.executor, func)
                    # We store the future in a map we the message data along to be able to ack/nack later
                    future_map[fut] = (msg_id, fields)

                pending = set(future_map.keys())
                while pending:
                    # We wait for the first future to complete
                    # And we loop again
                    done, pending = await asyncio.wait(
                        pending, return_when=asyncio.FIRST_COMPLETED
                    )
                    for fut in done:
                        msg_id, fields = future_map[fut]
                        # We check if the future raised an exception
                        try:
                            fut.result()
                        # If the processing raised a RetryableException, we requeue the message with an incremented retry count
                        except RetryableException as retry_exc:
                            logger.warning(
                                f"Échec de traitement du message {msg_id}: {retry_exc} retry it"
                            )
                            # We get the data stored along the future to re-send the message in the queue
                            retry_count = int(fields.get("retries", "0"))
                            data = fields.get("data", "")
                            # If the retry number is not exceeded, we requeue the message
                            if retry_count < self.max_retry_number - 1:
                                try:
                                    await self.redis.xadd(
                                        self.stream_name,
                                        {"data": data, "retries": str(retry_count + 1)},
                                    )
                                    logger.info(
                                        f"Message {msg_id} requeued with retry count {retry_count + 1}"
                                    )
                                # If we have an error during the requeue, we log it and move the message to the DLQ
                                except Exception as requeue_err:
                                    logger.error(
                                        f"Failed to requeue message {msg_id}: {requeue_err}"
                                    )
                                    # Push to DLQ if we cannot requeue
                                    await self._send_to_dlq(
                                        redis_connection=self.redis,
                                        msg_id=msg_id,
                                        fields=fields,
                                        reason="error_requeueing_message",
                                        error=str(requeue_err),
                                    )
                            else:
                                logger.error(
                                    f"Max retry count exceeded for message {msg_id}. Moving to DLQ."
                                )
                                await self._send_to_dlq(
                                    redis_connection=self.redis,
                                    msg_id=msg_id,
                                    fields=fields,
                                    reason="max_retries_exceeded",
                                    error=str(retry_exc),
                                )
                        # If we have an error that is not retryable, we log it and ack the message to remove it from the stream
                        # And move it to the DLQ
                        except Exception as proc_err:
                            logger.error(
                                f"Echec traitement message {msg_id}: {proc_err}. Moving to DLQ."
                            )
                            await self._send_to_dlq(
                                redis_connection=self.redis,
                                msg_id=msg_id,
                                fields=fields,
                                reason="not_retryable_error",
                                error=str(proc_err),
                            )
                        try:
                            logger.info("Message successfully acknowledged")
                            await self.redis.xack(
                                self.stream_name, self.consumer_group, msg_id
                            )
                        except Exception as ack_err:
                            logger.error(
                                f"Erreur ACK message {msg_id}: {ack_err} (risk de retraitement)."
                            )

        except Exception as e:
            logger.error(f"Error in consumer loop shutdown: {e}")
            self.stop_flag.set()
            raise e

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
            loop.run_until_complete(self.process_message_callable(message, retry_count))
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
                        await self.redis.xack(
                            self.stream_name, self.consumer_group, msg_id
                        )
                        logger.info(f"Acknowledged reclaimed message {msg_id}")
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
