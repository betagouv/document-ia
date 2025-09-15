import asyncio
import logging
from typing import Optional

from redis.asyncio import Redis, ConnectionPool

from document_ia_redis.redis_settings import redis_settings

logger = logging.getLogger(__name__)


class RedisManager:
    def __init__(self):
        self.redis: Optional[Redis] = None
        self.connection_attempts = 0
        self.max_retries = 3
        self.base_delay = 1.0
        self.max_delay = 30.0

    async def _get_retry_delay(self) -> float:
        """Calculate exponential backoff delay with jitter."""
        import random

        delay = min(self.base_delay * (2**self.connection_attempts), self.max_delay)
        jitter = delay * 0.25 * random.uniform(-1, 1)
        return max(0.1, delay + jitter)

    async def get_connection(self) -> Redis | None:
        """Ensure Redis connection with retry logic."""
        while self.connection_attempts < self.max_retries:
            try:
                if self.redis is None:
                    # Create connection pool
                    pool = ConnectionPool.from_url(
                        redis_settings.get_redis_url(),
                        decode_responses=True,
                        max_connections=20,
                    )
                    self.redis = Redis(connection_pool=pool)

                await self.redis.ping()
                if self.connection_attempts > 0:
                    logger.info(
                        f"Redis connection restored after {self.connection_attempts} attempts"
                    )
                self.connection_attempts = 0
                return self.redis

            except (ConnectionError, TimeoutError) as e:
                self.connection_attempts += 1
                delay = await self._get_retry_delay()
                logger.warning(
                    f"Redis connection failed (attempt {self.connection_attempts}/{self.max_retries}): {e}. "
                    f"Retrying in {delay:.2f}s"
                )
                await asyncio.sleep(delay)

        logger.error("Max Redis connection retries exceeded")
        return None

    async def close(self):
        if self.redis is not None:
            await self.redis.close()


redis_manager = RedisManager()
