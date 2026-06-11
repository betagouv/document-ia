import logging
from datetime import datetime, timedelta
from typing import Tuple

from redis.exceptions import ConnectionError, TimeoutError

from document_ia_infra.redis.redis_manager import redis_manager
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_api.infra.config import settings
from document_ia_api.infra.redis.redis_connectivity_status import (
    RedisConnectivityStatus,
)
from document_ia_api.schemas.rate_limiting import RateLimitInfo

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

    async def check_connectivity(self) -> RedisConnectivityStatus:
        """
        Comprehensive Redis connectivity check.

        Performs basic connection test (ping)

        Returns:
            Dict containing connectivity status and details
        """
        connectivity_status = RedisConnectivityStatus.default(
            host=redis_settings.REDIS_HOST,
            port=redis_settings.REDIS_PORT,
            db=redis_settings.REDIS_DB,
        )

        try:
            logger.info("Testing Redis connectivity...")
            connection = await redis_manager.get_connection()
            if connection is None:
                error_msg = "Failed to establish Redis connection"
                connectivity_status.errors.append(error_msg)
                logger.error(error_msg)
                return connectivity_status

            connectivity_status.connected = True
            connectivity_status.is_healthy = True
            logger.info("Redis connection established successfully")

            # Check number of messages to process in the queue
            try:
                lag, pending = await self.check_event_stream_lag()
                connectivity_status.lag = lag
                connectivity_status.pending = pending
                # Keep backward compatibility for nb_execution_to_process:
                if lag is not None and pending is not None:
                    connectivity_status.nb_execution_to_process = lag + pending
                elif lag is not None:
                    connectivity_status.nb_execution_to_process = lag
                else:
                    connectivity_status.nb_execution_to_process = pending
            except Exception as lag_err:
                logger.error(
                    f"Failed to check event stream lag during connectivity check: {lag_err}"
                )

        except (ConnectionError, TimeoutError) as e:
            error_msg = f"Redis connection failed: {e}"
            connectivity_status.errors.append(error_msg)
            logger.error(error_msg)
            return connectivity_status

        except Exception as e:
            error_msg = f"Unexpected error during Redis connectivity check: {e}"
            connectivity_status.errors.append(error_msg)
            logger.error(error_msg)
            return connectivity_status

        return connectivity_status

    async def check_event_stream_lag(self) -> Tuple[int | None, int | None]:
        """
        Check the number of waiting messages in the event stream (lag)
        and pending messages (read but not yet ACKed) for the group.
        """
        connection = await redis_manager.get_connection()
        if connection is None:
            logger.error("Redis connection unavailable for stream lag check")
            return None, None

        stream_name = redis_settings.EVENT_STREAM_NAME
        group_name = redis_settings.EVENT_CONSUMER_GROUP

        try:
            # Get information about consumer groups
            groups = await connection.xinfo_groups(stream_name)
            for group in groups:
                if group.get("name") == group_name:
                    lag = group.get("lag")
                    pending = group.get("pending")

                    lag_val = int(lag) if lag is not None else None
                    pending_val = int(pending) if pending is not None else None
                    return lag_val, pending_val

            # If the group was not found, fallback to total stream length as lag, pending=0.
            xlen = await connection.xlen(stream_name)
            return xlen, 0

        except Exception as e:
            err_msg = str(e).lower()
            if "no such key" in err_msg:
                # The stream doesn't exist yet
                return 0, 0
            elif "no such group" in err_msg:
                # The group does not exist yet
                try:
                    xlen = await connection.xlen(stream_name)
                    return xlen, 0
                except Exception:
                    return 0, 0
            else:
                logger.error(f"Error checking Redis stream groups: {e}")
                return None, None

    async def close(self):
        """Close Redis connection."""
        await redis_manager.close()


# Global Redis service instance
redis_service = RedisService()
