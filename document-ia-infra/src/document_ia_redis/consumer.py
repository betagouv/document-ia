"""
Classe Consumer commune pour les consumers Redis Stream
"""

import asyncio  # remplacement de threading+sleep
import logging
from asyncio import Future
from typing import TypeVar, Generic, Optional, Any

from document_ia_worker.core.threading.AsyncThread import AsyncThread
from redis import ResponseError
from redis.asyncio import Redis

from document_ia_redis.redis_manager import redis_manager, RedisManager
from document_ia_redis.serializable_message import SerializableMessage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SerializableMessage)

RECLAIM_IDLE_MS = 10000


class Consumer(Generic[T]):
    def __init__(
        self,
        consumer_name: str,
        consumer_group: str,
        stream_name: str,
        batch_size: int,
        block_time: int,
        worker_number: int = 1,
    ):
        """Initialise la connexion Redis et le consumer"""
        self.redis: Optional[Redis] = None
        self.reclaimer_thread: Optional[Future[Any]] = None
        self.consumer_name = consumer_name
        self.stream_name = stream_name
        self.consumer_group = consumer_group

        # Configuration du consumer
        self.batch_size = batch_size
        self.block_time = block_time  # en ms pour xreadgroup
        self.worker_number = worker_number
        self.stop_flag = False

    async def start_consumer(self):
        logger.info(f"Start consumer {self.consumer_name}")
        logger.debug("Establishing connection to Redis...")

        try:
            await self._init_consumer()
        except (ConnectionError, Exception) as e:
            logger.error(f"❌ Failed to start consumer {self.consumer_name}: {e}")
            return

        # Lancement de la tâche de réclamation asynchrone
        self._start_reclaimer_task()

        while not self.stop_flag:
            pass

        logger.info(f"Consumer {self.consumer_name} stopped")
        if self.reclaimer_thread is not None:
            logger.info("Waiting for reclaimer task to finish...")
            # Signale d'arrêt déjà posé par stop_flag
            await self.reclaimer_thread
        await redis_manager.close()

    def stop_signal(self):
        logger.info(f"need to shut down consumer {self.consumer_name}")
        self.stop_flag = True

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
        self.redis = await redis_manager.get_connection()
        if self.redis is None:
            logger.error("❌ No Redis connection available, cannot start consumer")
            raise ConnectionError("No Redis connection available")
        return self.redis

    def _start_reclaimer_task(self):
        if self.reclaimer_thread is not None:
            return

        async_thread = AsyncThread(
            target=self._reclaim_pending_messages(),
            name=f"reclaimer-{self.consumer_name}",
            daemon=True,
        )

        self.reclaimer_thread = async_thread.start()
        logger.info(
            f"Reclaimer daemon thread started for consumer {self.consumer_name}"
        )

    async def _reclaim_pending_messages(self):
        threaded_redis_manger = RedisManager()
        logger.info(f"Reclaimer task started idle_ms = {RECLAIM_IDLE_MS}")
        start = "0-0"

        redis_connection = await threaded_redis_manger.get_connection()
        if redis_connection is None:
            logger.error("❌ No Redis connection available for reclaimer")
            return

        # Boucle continue jusqu'à stop_flag
        while not self.stop_flag:
            try:
                next_start, claimed, _ = await redis_connection.xautoclaim(
                    self.stream_name,
                    self.consumer_group,
                    self.consumer_name,
                    RECLAIM_IDLE_MS,
                    start,
                    count=1,
                )
                for msg_id, fields in claimed:
                    logger.info(f"Reclaimed message ID: {msg_id} with fields: {fields}")
                    retries = int(fields.get("retries", "0")) + 1
                    fields["retries"] = str(retries)
                    # TODO : add DLQ handling if retries > max_retries
                    try:
                        await redis_connection.xack(
                            self.stream_name, self.consumer_group, msg_id
                        )
                        await redis_connection.xadd(self.stream_name, fields)
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
        await threaded_redis_manger.close()
        logger.info("Reclaimer task stopped")
