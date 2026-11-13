import asyncio
import logging
import random

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import AuthenticationError, ConnectionError, TimeoutError

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

    @staticmethod
    def _build_pool(url: str) -> Redis:
        pool = ConnectionPool.from_url(  # type: ignore[UnknownMemberType]
            url,
            decode_responses=True,
            max_connections=20,
            socket_connect_timeout=5,
            # Consumers block up to 10s on XREADGROUP (BLOCK 10000). redis-py 8
            # defaults socket_timeout to 5s, which would abort those reads with
            # a TimeoutError, so the read timeout is disabled explicitly here.
            socket_timeout=None,
        )
        return Redis(connection_pool=pool)

    async def get_connection(self) -> Redis | None:
        """Ensure Redis connection with retry logic."""
        # A previous outage must not disable recovery on every future request.
        for attempt in range(self.max_retries):
            try:
                if self.redis is None:
                    self.redis = self._build_pool(redis_settings.get_redis_url())

                await asyncio.wait_for(self.redis.ping(), timeout=5)  # type: ignore[misc]
                if self.connection_attempts > 0:
                    logger.info(
                        "Redis connection restored after %d attempts",
                        self.connection_attempts,
                    )
                self.connection_attempts = 0
                return self.redis

            except AuthenticationError as e:
                if "without any password configured" in str(e):
                    logger.warning(
                        "Redis password was provided but server has no password configured. Reconnecting without password."
                    )
                    if self.redis is not None:
                        await self.redis.aclose(close_connection_pool=True)
                    # Keep the endpoint get_redis_url() selected (host, port,
                    # database, scheme, options) and drop only the credentials.
                    self.redis = self._build_pool(
                        redis_settings.get_redis_url_without_credentials()
                    )
                    await asyncio.wait_for(self.redis.ping(), timeout=5)  # type: ignore[misc]
                    self.connection_attempts = 0
                    return self.redis
                self.connection_attempts = attempt + 1
                delay = await self._get_retry_delay()
                logger.warning(
                    "Redis connection failed (attempt %d/%d): %s. Retrying in %.2fs",
                    self.connection_attempts,
                    self.max_retries,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
            except (ConnectionError, TimeoutError, Exception) as e:
                self.connection_attempts = attempt + 1
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
        """Close client AND the explicitly constructed pool on the owning loop."""
        if self.redis is not None:
            await self.redis.aclose(close_connection_pool=True)
            self.redis = None
            self.connection_attempts = 0


redis_manager = RedisManager()
