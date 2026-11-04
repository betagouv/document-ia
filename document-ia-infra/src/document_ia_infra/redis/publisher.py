"""
Class Publisher for Redis Stream
"""

import json
import logging
from datetime import datetime
from typing import TypeVar, Generic

from redis.exceptions import RedisError
from redis.typing import EncodableT

from document_ia_infra.redis.redis_manager import redis_manager, RedisManager
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_infra.redis.serializable_message import SerializableMessage
from document_ia_infra.redis.admission import admit_execution

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SerializableMessage)


class PublishFailedError(Exception):
    """The message could not be scheduled on the Redis stream.

    Raised instead of returning ``None`` so callers can distinguish a scheduling
    failure from a successful publication and must decide the resulting state.
    """

    def __init__(self, stream_name: str, reason: str):
        self.stream_name = stream_name
        self.reason = reason
        super().__init__(f"Publication on Redis stream {stream_name} failed: {reason}")


class Publisher(Generic[T]):
    def __init__(
        self, stream_name: str, current_redis_manager: RedisManager = redis_manager
    ):
        """Initialise the Redis connection and the publisher"""
        self.stream_name = stream_name
        self.current_redis_manager = current_redis_manager

    async def publish_message(self, message: T):
        """Publie une tâche dans le stream Redis.

        Returns the Redis message id on success.

        Raises:
            PublishFailedError: when no connection is available or Redis refuses
                the write. The exception message never embeds the published
                payload.

        New workflow messages allocate capacity atomically against both queues.
        Other publications can drain accepted work. Never trim unfinished work.
        """
        try:
            connection = await self.current_redis_manager.get_connection()
        except RedisError as e:
            logger.error("❌ Redis connection failed: %s", e)
            raise PublishFailedError(self.stream_name, type(e).__name__) from e

        if connection is None:
            logger.error("❌ No Redis connection available")
            raise PublishFailedError(self.stream_name, "no_connection")

        try:
            # Convertir les données en format approprié pour Redis
            stream_data: dict[EncodableT, EncodableT] = {
                "data": json.dumps(message.to_dict()),
                "timestamp": datetime.now().isoformat(),
                "retries": 0,
            }

            if self.stream_name == redis_settings.EVENT_STREAM_NAME:
                message_id = await admit_execution(
                    connection,
                    data=str(stream_data["data"]),
                    timestamp=str(stream_data["timestamp"]),
                )
            else:
                message_id = await connection.xadd(self.stream_name, stream_data)

            logger.info(f"✅ Message published in Redis stream: {message_id}")

            return message_id
        except Exception as e:
            logger.error(f"❌ Error publishing message in Redis stream: {e}")
            raise PublishFailedError(self.stream_name, type(e).__name__) from e
