"""
Class Publisher for Redis Stream
"""

import asyncio
import json
import logging
from collections.abc import Awaitable
from datetime import datetime
from typing import TypeVar, Generic, cast

from redis.exceptions import RedisError
from redis.typing import EncodableT

from document_ia_infra.redis.redis_manager import redis_manager, RedisManager
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_infra.redis.serializable_message import SerializableMessage
from document_ia_infra.redis.admission import admit_execution
from document_ia_infra.redis.idempotent_publish import IDEMPOTENT_PUBLISH_SCRIPT

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


class ReservationLostError(Exception):
    """The idempotency reservation was lost before the publication.

    Raised by the fenced publication when the ownership check inside the same
    Redis operation failed: another request owns the key, so nothing was
    written. Publishing here would duplicate the execution.
    """


class PublicationOutcomeUnknownError(PublishFailedError):
    """The publication may or may not have been applied.

    Raised when the fenced script's reply is lost (timeout, dropped connection).
    Redis may have committed the XADD and marked the reservation COMPLETED. The
    caller must not report a scheduling failure: doing so invites a retry that
    would publish the same work twice.
    """


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

    async def publish_message_fenced(
        self,
        message: T,
        *,
        reservation_key: str,
        reservation_execution_id: str,
        reservation_ttl_seconds: int,
    ) -> str:
        """Publish only while this request still owns its idempotency reservation.

        Ownership, capacity admission and the stream write happen in one Redis
        script, so the key cannot expire or be re-acquired between the check and
        the XADD. A separate pre-check is not enough: the publisher awaits its
        connection in between, and a stale request would then publish a second
        execution.

        Raises:
            ReservationLostError: the reservation is no longer ours; nothing was
                written.
            PublishFailedError: no connection, or capacity was exhausted.
        """
        try:
            connection = await self.current_redis_manager.get_connection()
        except RedisError as e:
            logger.error("❌ Redis connection failed: %s", e)
            raise PublishFailedError(self.stream_name, type(e).__name__) from e

        if connection is None:
            logger.error("❌ No Redis connection available")
            raise PublishFailedError(self.stream_name, "no_connection")

        stream_data = {
            "data": json.dumps(message.to_dict()),
            "timestamp": datetime.now().isoformat(),
        }
        args = [
            reservation_execution_id,
            str(reservation_ttl_seconds),
            redis_settings.EVENT_CONSUMER_GROUP,
            redis_settings.WEBHOOK_CONSUMER_GROUP,
            str(redis_settings.ADMISSION_MAX_OUTSTANDING),
            str(redis_settings.ADMISSION_RESUME_OUTSTANDING),
            str(redis_settings.ADMISSION_MAX_AGE_SECONDS),
            str(redis_settings.ADMISSION_RESUME_AGE_SECONDS),
            "publish",
            stream_data["data"],
            stream_data["timestamp"],
            str(redis_settings.ADMISSION_MAX_RETAINED),
            str(redis_settings.ADMISSION_RESUME_RETAINED),
        ]
        keys = [
            reservation_key,
            redis_settings.EVENT_STREAM_NAME,
            redis_settings.WEBHOOK_STREAM_NAME,
            f"{redis_settings.EVENT_STREAM_NAME}:admission",
            f"{redis_settings.WEBHOOK_STREAM_NAME}:admission",
        ]
        # Bounded like the unfenced path (`admit_execution`): without a deadline a
        # stalled Redis holds the request and its pooled connection open.
        try:
            result = await asyncio.wait_for(
                cast(
                    Awaitable[list[object]],
                    connection.eval(  # type: ignore[UnknownMemberType]
                        IDEMPOTENT_PUBLISH_SCRIPT, len(keys), *keys, *args
                    ),
                ),
                timeout=redis_settings.PUBLISH_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, ConnectionError, RedisError) as e:
            # The write may have landed. Redis error replies (a Lua failure or a
            # malformed request) mean it did not, so only ambiguous transport
            # failures are reported as unknown.
            logger.error("❌ Publication outcome unknown: %s", e)
            raise PublicationOutcomeUnknownError(
                self.stream_name, type(e).__name__
            ) from e
        except Exception as e:
            logger.error("❌ Error publishing fenced message: %s", e)
            raise PublishFailedError(self.stream_name, type(e).__name__) from e

        if not result or result[0] == 0:
            raise ReservationLostError()
        if result[0] != 1:
            raise PublishFailedError(self.stream_name, "capacity_exhausted")
        message_id = result[1]
        if not isinstance(message_id, str):
            raise PublishFailedError(self.stream_name, "invalid_publication_response")
        return message_id
