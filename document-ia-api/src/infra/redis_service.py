import logging
from datetime import datetime, timedelta
from typing import Tuple, Dict, Any

from redis.exceptions import ConnectionError, TimeoutError

from document_ia_redis.redis_manager import redis_manager
from document_ia_redis.redis_settings import redis_settings
from infra.config import settings
from schemas.rate_limiting import RateLimitInfo

# TODO: add a proper logging service (remove pii and sanitize data)
logger = logging.getLogger(__name__)


# TODO: reset self.connection_attempts to 0 otherwise it will never reconnect


class RedisService:
    """Redis service for caching and rate limiting operations."""

    async def check_rate_limit(self, api_key: str) -> Tuple[bool, RateLimitInfo]:
        """
        Check rate limits for an API key.

        Args:
            api_key: The API key to check rate limits for

        Returns:
            Tuple[bool, RateLimitInfo]: (is_allowed, rate_limit_info)
        """
        connection = await redis_manager.get_connection()
        if connection is None:
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

            # Calculate proper window boundaries for fixed window rate limiting
            minute_start = now.replace(second=0, microsecond=0)
            next_minute = minute_start + timedelta(minutes=1)

            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            next_day = day_start + timedelta(days=1)

            minute_key = (
                f"rate_limit:minute:{api_key}:{minute_start.strftime('%Y%m%d%H%M')}"
            )
            daily_key = f"rate_limit:daily:{api_key}:{day_start.strftime('%Y%m%d')}"

            # Use pipeline for atomic operations
            async with connection.pipeline() as pipe:
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
                    reset_minute=next_minute.isoformat(),
                    reset_daily=next_day.isoformat(),
                )

            return True, RateLimitInfo(
                limit_exceeded=False,
                remaining_minute=settings.RATE_LIMIT_REQUESTS_PER_MINUTE - minute_count,
                remaining_daily=settings.RATE_LIMIT_REQUESTS_PER_DAY - daily_count,
                reset_minute=next_minute.isoformat(),
                reset_daily=next_day.isoformat(),
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
            "host": redis_settings.REDIS_HOST,
            "port": redis_settings.REDIS_PORT,
            "db": redis_settings.REDIS_DB,
            "errors": [],
        }

        try:
            logger.info("Testing Redis connectivity...")
            connection = await redis_manager.get_connection()
            if connection is None:
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
        await redis_manager.close()


# Global Redis service instance
redis_service = RedisService()
