import asyncio
import logging
import random

from redis.asyncio import ConnectionPool, Redis

from document_ia_infra.redis.redis_settings import redis_settings

logger = logging.getLogger(__name__)


class RedisManager:
    def __init__(self) -> None:
        self.redis: Redis | None = None
        self.connection_attempts = 0
        self.max_retries = 3
        self.base_delay = 1.0
        self.max_delay = 30.0

    async def _get_retry_delay(self) -> float:
        """Calculate exponential backoff delay with jitter."""
        delay = min(self.base_delay * (2**self.connection_attempts), self.max_delay)
        jitter = delay * 0.25 * random.uniform(-1, 1)
        return max(0.1, delay + jitter)

    async def get_connection(self) -> Redis | None:
        """Ensure Redis connection with retry logic."""
        self.connection_attempts = 0
        while self.connection_attempts < self.max_retries:
            try:
                if self.redis is None:
                    pool = ConnectionPool.from_url(  # type: ignore[UnknownMemberType]
                        redis_settings.get_redis_url(),
                        decode_responses=True,
                        max_connections=20,
                    )
                    self.redis = Redis(connection_pool=pool)

                await self.redis.ping()  # type: ignore[misc]
                if self.connection_attempts > 0:
                    logger.info(
                        "Redis connection restored after %d attempts",
                        self.connection_attempts,
                    )
                self.connection_attempts = 0
                return self.redis

            except Exception as e:
                self.connection_attempts += 1
                delay = await self._get_retry_delay()
                logger.warning(
                    "Redis connection failed (attempt %d/%d): %s. Retrying in %.2fs",
                    self.connection_attempts,
                    self.max_retries,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)

        if self.redis is not None:
            stale_client = self.redis
            self.redis = None
            try:
                await stale_client.close()
            except Exception:
                pass
        logger.error("Max Redis connection retries exceeded")
        return None

    async def close(self) -> None:
        if self.redis is not None:
            client = self.redis
            self.redis = None
            self.connection_attempts = 0
            await client.close()


redis_manager = RedisManager()
