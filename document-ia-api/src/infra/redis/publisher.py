#!/usr/bin/env python3
"""
Class Publisher for Redis Stream
"""

from infra.config import settings
import json
from datetime import datetime

import logging

logger = logging.getLogger(__name__)


class Publisher:
    def __init__(self, redis_client, stream_name):
        """Initialise the Redis connection and the publisher"""
        self.redis_client = redis_client
        self.stream_name = stream_name

    def publish_message(self, message):
        """Publie une tâche dans le stream Redis"""
        try:
            # Convertir les données en format approprié pour Redis
            stream_data = {
                "data": json.dumps(message),
                "timestamp": datetime.now().isoformat(),
            }

            # Ajouter au stream
            message_id = self.redis_client.xadd(
                self.stream_name,
                stream_data,
                maxlen=settings.EVENT_STREAM_MAXLEN,  # limit the size of the stream
                ex=settings.EVENT_STREAM_EXPIRATION,  # add an expiration
            )
            logger.info(f"✅ Message published in Redis stream: {message_id}")

            return message_id
        except Exception as e:
            logger.error(f"❌ Error publishing message in Redis stream: {e}")
            return None
