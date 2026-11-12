import logging
import asyncio
from datetime import datetime, timedelta
from typing import Any, Awaitable, Tuple, cast
from uuid import UUID

from redis.exceptions import ConnectionError, TimeoutError

from document_ia_infra.redis.redis_manager import redis_manager
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_api.infra.config import settings
from document_ia_api.infra.redis.redis_connectivity_status import (
    RedisConnectivityStatus,
)
from document_ia_api.schemas.rate_limiting import RateLimitInfo
from document_ia_api.api.exceptions.service_unavailable_exception import (
    capacity_unavailable,
)

logger = logging.getLogger(__name__)

RATE_LIMIT_SCRIPT = """
local minute_key = KEYS[1]
local daily_key = KEYS[2]
local minute_limit = tonumber(ARGV[1])
local daily_limit = tonumber(ARGV[2])
local minute_ttl = tonumber(ARGV[3])
local daily_ttl = tonumber(ARGV[4])

local minute_count = tonumber(redis.call('GET', minute_key) or '0')
local daily_count = tonumber(redis.call('GET', daily_key) or '0')

if minute_count >= minute_limit or daily_count >= daily_limit then
    return {0, minute_count, daily_count}
end

minute_count = redis.call('INCR', minute_key)
if minute_count == 1 or redis.call('TTL', minute_key) < 0 then
    redis.call('EXPIRE', minute_key, minute_ttl)
end

daily_count = redis.call('INCR', daily_key)
if daily_count == 1 or redis.call('TTL', daily_key) < 0 then
    redis.call('EXPIRE', daily_key, daily_ttl)
end

return {1, minute_count, daily_count}
"""


class RedisService:
    """Redis service for caching and rate limiting operations."""

    async def check_rate_limit(self, key_id: UUID | str) -> Tuple[bool, RateLimitInfo]:
        """
        Check rate limits for an API key by its identifier.

        Args:
            key_id: The API key identifier (UUID or str) to check rate limits for

        Returns:
            Tuple[bool, RateLimitInfo]: (is_allowed, rate_limit_info)
        """
        try:
            key_uuid = key_id if isinstance(key_id, UUID) else UUID(str(key_id))
        except (ValueError, TypeError) as exc:
            raise ValueError("key_id must be a valid UUID") from exc

        key_identifier = str(key_uuid)
        try:
            connection = await redis_manager.get_connection()
            if connection is None:
                raise ConnectionError("Quota connection unavailable")
            now = datetime.now()

            # Calculate proper window boundaries for fixed window rate limiting
            minute_start = now.replace(second=0, microsecond=0)
            next_minute = minute_start + timedelta(minutes=1)

            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            next_day = day_start + timedelta(days=1)

            minute_key = f"rate_limit:minute:{key_identifier}:{minute_start.strftime('%Y%m%d%H%M')}"
            daily_key = (
                f"rate_limit:daily:{key_identifier}:{day_start.strftime('%Y%m%d')}"
            )

            # Use pipeline for atomic operations
            async with connection.pipeline() as pipe:
                await cast(
                    Awaitable[Any],
                    pipe.eval(
                        RATE_LIMIT_SCRIPT,
                        2,
                        minute_key,
                        daily_key,
                        str(settings.RATE_LIMIT_REQUESTS_PER_MINUTE),
                        str(settings.RATE_LIMIT_REQUESTS_PER_DAY),
                        "60",
                        "86400",
                    ),
                )
                results = await asyncio.wait_for(pipe.execute(), timeout=5)
                eval_result = results[0]
                is_allowed = bool(int(eval_result[0]))
                minute_count = int(eval_result[1])
                daily_count = int(eval_result[2])

            if not is_allowed:
                logger.warning(
                    "Rate limit exceeded for API key identifier %s - "
                    "Minute: %s/%s, Daily: %s/%s",
                    key_identifier,
                    minute_count,
                    settings.RATE_LIMIT_REQUESTS_PER_MINUTE,
                    daily_count,
                    settings.RATE_LIMIT_REQUESTS_PER_DAY,
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

        except Exception as e:
            logger.error("Quota check unavailable: %s", type(e).__name__)
            raise capacity_unavailable() from e

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
                connectivity_status.nb_execution_undelivered = lag
                connectivity_status.nb_execution_being_processed = pending

                if lag is not None or pending is not None:
                    connectivity_status.nb_execution_to_process = (lag or 0) + (
                        pending or 0
                    )
                else:
                    connectivity_status.nb_execution_to_process = None
            except Exception as lag_err:
                logger.error(
                    "Failed to check event stream lag during connectivity check: %s",
                    lag_err,
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
                logger.error("Error checking Redis stream groups: %s", e)
                return None, None

    async def close(self):
        """Close Redis connection."""
        await redis_manager.close()


# Global Redis service instance
redis_service = RedisService()
