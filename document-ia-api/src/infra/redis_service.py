import asyncio
import logging
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timedelta
from redis.asyncio import Redis, ConnectionPool
from redis.exceptions import ConnectionError, TimeoutError

from infra.config import settings
from schemas.rate_limiting import RateLimitInfo

# TODO: add a proper logging service (remove pii and sanitize data)
logger = logging.getLogger(__name__)

# TODO: reset self.connection_attempts to 0 otherwise it will never reconnect


class RedisService:
    """Redis service for caching and rate limiting operations."""

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

    async def _ensure_connection(self) -> bool:
        """Ensure Redis connection with retry logic."""
        while self.connection_attempts < self.max_retries:
            try:
                if self.redis is None:
                    # Create connection pool
                    pool = ConnectionPool.from_url(
                        f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
                        password=settings.REDIS_PASSWORD,
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
                return True

            except (ConnectionError, TimeoutError) as e:
                self.connection_attempts += 1
                delay = await self._get_retry_delay()
                logger.warning(
                    f"Redis connection failed (attempt {self.connection_attempts}/{self.max_retries}): {e}. "
                    f"Retrying in {delay:.2f}s"
                )
                await asyncio.sleep(delay)

        logger.error("Max Redis connection retries exceeded")
        return False

    async def check_rate_limit(self, api_key: str) -> Tuple[bool, RateLimitInfo]:
        """
        Check rate limits for an API key.

        Args:
            api_key: The API key to check rate limits for

        Returns:
            Tuple[bool, RateLimitInfo]: (is_allowed, rate_limit_info)
        """
        if not await self._ensure_connection():
            # If Redis is unavailable, allow the request but log the issue
            logger.error(
                "Redis unavailable - allowing request but rate limiting is disabled"
            )
            return True, RateLimitInfo(
                limit_exceeded=False,
                remaining_minute=settings.RATE_LIMIT_REQUESTS_PER_MINUTE,
                remaining_daily=settings.RATE_LIMIT_REQUESTS_PER_DAY,
                reset_minute=None,
                reset_daily=None,
            )

        try:
            now = datetime.now()
            minute_key = f"rate_limit:minute:{api_key}:{now.strftime('%Y%m%d%H%M')}"
            daily_key = f"rate_limit:daily:{api_key}:{now.strftime('%Y%m%d')}"

            # Use pipeline for atomic operations
            async with self.redis.pipeline() as pipe:
                # Increment counters and get current values
                await pipe.incr(minute_key)
                await pipe.expire(minute_key, 60)  # Expire after 60 seconds
                await pipe.incr(daily_key)
                await pipe.expire(daily_key, 86400)  # Expire after 24 hours

                # Get current values
                await pipe.get(minute_key)
                await pipe.get(daily_key)

                results = await pipe.execute()

                minute_count = int(results[4])
                daily_count = int(results[5])

            # Check limits
            minute_exceeded = minute_count > settings.RATE_LIMIT_REQUESTS_PER_MINUTE
            daily_exceeded = daily_count > settings.RATE_LIMIT_REQUESTS_PER_DAY

            if minute_exceeded or daily_exceeded:
                logger.warning(
                    f"Rate limit exceeded for API key {api_key[:8]}... - "
                    f"Minute: {minute_count}/{settings.RATE_LIMIT_REQUESTS_PER_MINUTE}, "
                    f"Daily: {daily_count}/{settings.RATE_LIMIT_REQUESTS_PER_DAY}"
                )
                return False, RateLimitInfo(
                    limit_exceeded=True,
                    remaining_minute=max(
                        0, settings.RATE_LIMIT_REQUESTS_PER_MINUTE - minute_count
                    ),
                    remaining_daily=max(
                        0, settings.RATE_LIMIT_REQUESTS_PER_DAY - daily_count
                    ),
                    reset_minute=(now + timedelta(minutes=1)).isoformat(),
                    reset_daily=(now + timedelta(days=1)).isoformat(),
                )

            return True, RateLimitInfo(
                limit_exceeded=False,
                remaining_minute=settings.RATE_LIMIT_REQUESTS_PER_MINUTE - minute_count,
                remaining_daily=settings.RATE_LIMIT_REQUESTS_PER_DAY - daily_count,
                reset_minute=(now + timedelta(minutes=1)).isoformat(),
                reset_daily=(now + timedelta(days=1)).isoformat(),
            )

        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis error during rate limit check: {e}")
            # Allow request if Redis fails
            return True, RateLimitInfo(
                limit_exceeded=False,
                remaining_minute=settings.RATE_LIMIT_REQUESTS_PER_MINUTE,
                remaining_daily=settings.RATE_LIMIT_REQUESTS_PER_DAY,
                reset_minute=None,
                reset_daily=None,
            )
        except Exception as e:
            logger.error(f"Unexpected error during rate limit check: {e}")
            # Allow request on unexpected errors
            return True, RateLimitInfo(
                limit_exceeded=False,
                remaining_minute=settings.RATE_LIMIT_REQUESTS_PER_MINUTE,
                remaining_daily=settings.RATE_LIMIT_REQUESTS_PER_DAY,
                reset_minute=None,
                reset_daily=None,
            )

    async def check_connectivity(self) -> Dict[str, Any]:
        """
        Comprehensive Redis connectivity check.

        Performs basic connection test (ping)

        Returns:
            Dict containing connectivity status and details
        """
        connectivity_status = {
            "connected": False,
            "is_healthy": False,
            "host": settings.REDIS_HOST,
            "port": settings.REDIS_PORT,
            "db": settings.REDIS_DB,
            "errors": [],
        }

        try:
            logger.info("Testing Redis connectivity...")
            if not await self._ensure_connection():
                error_msg = "Failed to establish Redis connection"
                connectivity_status["errors"].append(error_msg)
                logger.error(error_msg)
                return connectivity_status

            connectivity_status["connected"] = True
            connectivity_status["is_healthy"] = True
            logger.info("Redis connection established successfully")

        except (ConnectionError, TimeoutError) as e:
            error_msg = f"Redis connection failed: {e}"
            connectivity_status["errors"].append(error_msg)
            logger.error(error_msg)
            return connectivity_status

        except Exception as e:
            error_msg = f"Unexpected error during Redis connectivity check: {e}"
            connectivity_status["errors"].append(error_msg)
            logger.error(error_msg)
            return connectivity_status

        return connectivity_status

    async def close(self):
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()


# Global Redis service instance
redis_service = RedisService()
