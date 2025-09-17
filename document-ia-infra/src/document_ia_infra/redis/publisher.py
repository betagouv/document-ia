"""
Class Publisher for Redis Stream
"""

import json
import logging
from datetime import datetime
from typing import TypeVar, Generic

from redis.typing import EncodableT

from document_ia_infra.redis.redis_manager import redis_manager
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_infra.redis.serializable_message import SerializableMessage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SerializableMessage)


class Publisher(Generic[T]):
    def __init__(self, stream_name: str):
        """Initialise the Redis connection and the publisher"""
        self.stream_name = stream_name

    async def publish_message(self, message: T):
        """Publie une tâche dans le stream Redis"""
        try:
            connection = await redis_manager.get_connection()
            if connection is None:
                logger.error("❌ No Redis connection available")
                return None

            # Convertir les données en format approprié pour Redis
            stream_data: dict[EncodableT, EncodableT] = {
                "data": json.dumps(message.to_dict()),
                "timestamp": datetime.now().isoformat(),
                "retries": 0,
            }

            # Ajouter au stream
            # WARNING = inside a stream there is no ttl or expiration mechanism we have to implement it !
            message_id = await connection.xadd(
                self.stream_name,
                stream_data,
                maxlen=redis_settings.EVENT_STREAM_MAXLEN,  # limit the size of the stream
            )

            logger.info(f"✅ Message published in Redis stream: {message_id}")

            return message_id
        except Exception as e:
            logger.error(f"❌ Error publishing message in Redis stream: {e}")
            return None
