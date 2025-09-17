"""
Classe Consumer commune pour les consumers Redis Stream
"""

import asyncio  # remplacement de threading+sleep
import logging
from asyncio import Task
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar, Generic, Optional, Any

from redis import ResponseError
from redis.asyncio import Redis

from document_ia_infra.redis.redis_manager import (
    redis_manager as redis_manager_main_thread,
)
from document_ia_infra.redis.serializable_message import SerializableMessage

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
        self.redis: Optional[Redis] = None
        self.reclaimer_task: Optional[Task[Any]] = None
        self.stop_flag = asyncio.Event()
        self.consumer_name = consumer_name
        self.stream_name = stream_name
        self.consumer_group = consumer_group

        # Configuration du consumer
        self.batch_size = batch_size
        self.block_time = block_time  # en ms pour xreadgroup
        self.worker_number = worker_number

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
                for msg in entries:
                    message_data: T = msg[1]["data"]
                    logger.info(f"Received message: {msg} with data : {message_data}")
                    await self.redis.xack(self.stream_name, self.consumer_group, msg[0])
                    raise NotImplementedError("Process the message here")

        except Exception as e:
            logger.error(f"Error in consumer loop shutdown: {e}")
            self.stop_flag.set()
            raise e

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
                    retries = int(fields.get("retries", "0")) + 1
                    fields["retries"] = str(retries)
                    # TODO : add DLQ handling if retries > max_retries
                    try:
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
