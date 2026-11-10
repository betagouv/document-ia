import asyncio
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import logging
from typing import Any, cast
from uuid import UUID

from redis.asyncio import Redis

from document_ia_api.api.exceptions.service_unavailable_exception import (
    capacity_unavailable,
)
from document_ia_api.core.idempotency.exceptions import (
    IdempotencyConflictException,
    IdempotencyInProgressException,
    IdempotencyReservationLostException,
)
from document_ia_api.core.idempotency.models import (
    IdempotencyEntry,
    IdempotencyResult,
    IdempotencyStatus,
)
from document_ia_infra.redis.publisher import (
    PublicationOutcomeUnknownError,
    ReservationLostError,
)
from document_ia_infra.redis.redis_manager import redis_manager
from document_ia_infra.redis.redis_settings import redis_settings

logger = logging.getLogger(__name__)

ACQUIRE_OR_CHECK_LUA = """
local existing = redis.call('GET', KEYS[1])
if existing then
    return existing
else
    redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
    return nil
end
"""

MARK_COMPLETED_LUA = """
local existing = redis.call('GET', KEYS[1])
if existing then
    local ok, data = pcall(cjson.decode, existing)
    if ok and data['execution_id'] == ARGV[1] then
        data['status'] = 'COMPLETED'
        redis.call('SET', KEYS[1], cjson.encode(data), 'EX', tonumber(ARGV[2]))
        return 1
    end
end
return 0
"""

# Completion tracking must not fail open, and must never leave an accepted
# execution recorded as IN_PROGRESS (that would return 409 forever instead of
# replaying). One atomic operation: complete our entry, recreate it as COMPLETED
# if it lapsed, and never clobber a key another request now owns.
# Returns 1 when an accepted mapping was written, 0 when the key belongs to
# another request and nothing could be recorded.
COMPLETE_OR_RETAIN_LUA = """
local existing = redis.call('GET', KEYS[1])
if existing then
    local ok, data = pcall(cjson.decode, existing)
    if not ok then return 0 end
    if data['execution_id'] ~= ARGV[1] then
        -- Another request owns the key now; publishing here would have been a
        -- duplicate, so there is nothing safe to record.
        return 0
    end
    data['status'] = 'COMPLETED'
    redis.call('SET', KEYS[1], cjson.encode(data), 'EX', tonumber(ARGV[2]))
    return 1
end
-- The reservation lapsed after acceptance: recreate the mapping so the
-- accepted execution stays replayable instead of being scheduled twice.
redis.call('SET', KEYS[1], ARGV[3], 'EX', tonumber(ARGV[2]))
return 1
"""

# Renew only while the entry is still ours and still in progress: a completed
# entry must keep its retention TTL, and a re-acquired key belongs to someone
# else.
RENEW_LEASE_LUA = """
local existing = redis.call('GET', KEYS[1])
if existing then
    local ok, data = pcall(cjson.decode, existing)
    if ok and data['execution_id'] == ARGV[1] and data['status'] == 'IN_PROGRESS' then
        return redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
    end
end
return 0
"""


# Release only un-published reservations. A COMPLETED entry records an execution
# that was accepted: deleting it lets the next retry schedule the work again, so
# cleanup must never touch it. That matters most when a publication succeeded but
# its reply was lost, which looks like a failure to the caller.
RELEASE_KEY_LUA = """
if ARGV[1] ~= '' then
    local existing = redis.call('GET', KEYS[1])
    if existing then
        local ok, data = pcall(cjson.decode, existing)
        if ok and data['execution_id'] == ARGV[1] and data['status'] == 'IN_PROGRESS' then
            redis.call('DEL', KEYS[1])
            return 1
        end
    end
    return 0
else
    return redis.call('DEL', KEYS[1])
end
"""


def build_idempotency_redis_key(
    *,
    version: int | str,
    organization_id: UUID | str,
    workflow_id: str,
    idempotency_key: str,
) -> str:
    """Construct isolated Redis key for idempotency tracking."""
    return f"idempotency:v{version}:{organization_id}:{workflow_id}:{idempotency_key}"


class IdempotencyService:
    """Service managing idempotency locks, replay detection and retention in Redis."""

    def __init__(self, redis_client: Redis | None = None) -> None:
        self._redis_client = redis_client

    async def _get_connection(self) -> Redis:
        if self._redis_client is not None:
            return self._redis_client
        connection = await redis_manager.get_connection()
        if connection is None:
            raise capacity_unavailable()
        return connection

    async def acquire_or_check(
        self,
        *,
        key: str,
        fingerprint: str,
        execution_id: str,
        lock_ttl_seconds: int | None = None,
    ) -> IdempotencyResult:
        """Atomically acquire the idempotency lock or check existing submission.

        - If key does not exist: sets status to IN_PROGRESS with lock TTL and returns (is_replay=False).
        - If key exists with status COMPLETED and identical fingerprint: returns (is_replay=True).
        - If key exists with different fingerprint: raises IdempotencyConflictException (409).
        - If key exists with status IN_PROGRESS: raises IdempotencyInProgressException (409).
        """
        connection = await self._get_connection()
        ttl = lock_ttl_seconds or redis_settings.IDEMPOTENCY_LOCK_TTL_SECONDS
        entry = IdempotencyEntry(
            fingerprint=fingerprint,
            execution_id=execution_id,
            status=IdempotencyStatus.IN_PROGRESS,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        entry_json = entry.model_dump_json()

        try:
            raw_result = await asyncio.wait_for(
                cast(
                    Awaitable[Any],
                    connection.eval(  # type: ignore[UnknownMemberType]
                        ACQUIRE_OR_CHECK_LUA,
                        1,
                        key,
                        entry_json,
                        str(ttl),
                    ),
                ),
                timeout=5,
            )
        except Exception as exc:
            logger.error("Failed to execute acquire_or_check on Redis: %s", exc)
            raise capacity_unavailable() from exc

        if raw_result is None:
            # Key acquired (Miss)
            return IdempotencyResult(is_replay=False, execution_id=execution_id)

        # Hit: existing entry returned
        if not isinstance(raw_result, str):
            raw_str = (
                raw_result.decode("utf-8")
                if isinstance(raw_result, bytes)
                else str(raw_result)
            )
        else:
            raw_str = raw_result

        try:
            existing = IdempotencyEntry.model_validate_json(raw_str)
        except Exception as exc:
            logger.error("Corrupted idempotency entry in Redis (%s): %s", key, exc)
            raise IdempotencyConflictException() from exc

        if existing.fingerprint != fingerprint:
            raise IdempotencyConflictException()

        if existing.status == IdempotencyStatus.IN_PROGRESS:
            raise IdempotencyInProgressException(execution_id=existing.execution_id)

        # Replay hit
        return IdempotencyResult(
            is_replay=True,
            execution_id=existing.execution_id,
        )

    async def mark_completed(
        self,
        *,
        key: str,
        execution_id: str,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Mark an execution as COMPLETED with long retention TTL."""
        try:
            connection = await self._get_connection()
            ttl = ttl_seconds or redis_settings.IDEMPOTENCY_KEY_TTL_SECONDS
            result = await asyncio.wait_for(
                cast(
                    Awaitable[Any],
                    connection.eval(  # type: ignore[UnknownMemberType]
                        MARK_COMPLETED_LUA,
                        1,
                        key,
                        execution_id,
                        str(ttl),
                    ),
                ),
                timeout=5,
            )
            return bool(result == 1)
        except Exception as exc:
            logger.error("Failed to mark idempotency key as completed: %s", exc)
            return False

    async def renew(
        self,
        *,
        key: str,
        execution_id: str,
        lock_ttl_seconds: int | None = None,
    ) -> bool:
        """Extend the reservation TTL while the entry is still ours and in progress.

        Used to keep a slow admission attempt protected past the short lock TTL,
        and as a fallback retention extension when completion tracking fails.
        Returns ``False`` when the entry is gone, completed, or now owned by
        another request.
        """
        try:
            connection = await self._get_connection()
            ttl = lock_ttl_seconds or redis_settings.IDEMPOTENCY_LOCK_TTL_SECONDS
            result = await asyncio.wait_for(
                cast(
                    Awaitable[Any],
                    connection.eval(  # type: ignore[UnknownMemberType]
                        RENEW_LEASE_LUA,
                        1,
                        key,
                        execution_id,
                        str(ttl),
                    ),
                ),
                timeout=5,
            )
            return bool(result == 1)
        except Exception as exc:
            logger.warning("Failed to renew idempotency key %s: %s", key, exc)
            return False

    async def complete_or_retain(
        self,
        *,
        key: str,
        execution_id: str,
        fingerprint: str,
        created_at: str,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Record an accepted execution as completed, or recreate its mapping.

        Never leaves an accepted execution recorded as `IN_PROGRESS`, which would
        answer every retry with 409 instead of replaying it, and never lapses,
        which would let a retry schedule the work twice. Returns False only when
        another request owns the key.
        """
        try:
            connection = await self._get_connection()
            ttl = ttl_seconds or redis_settings.IDEMPOTENCY_KEY_TTL_SECONDS
            entry = IdempotencyEntry(
                fingerprint=fingerprint,
                execution_id=execution_id,
                status=IdempotencyStatus.COMPLETED,
                created_at=created_at,
            )
            result = await asyncio.wait_for(
                cast(
                    Awaitable[Any],
                    connection.eval(  # type: ignore[UnknownMemberType]
                        COMPLETE_OR_RETAIN_LUA,
                        1,
                        key,
                        execution_id,
                        str(ttl),
                        entry.model_dump_json(),
                    ),
                ),
                timeout=5,
            )
            return bool(result == 1)
        except Exception as exc:
            logger.error(
                "Failed to record accepted execution %s under key %s: %s",
                execution_id,
                key,
                exc,
            )
            return False

    async def release_key(
        self,
        *,
        key: str,
        execution_id: str | None = None,
    ) -> bool:
        """Release the idempotency key (e.g. after a scheduling failure) to permit immediate retry."""
        try:
            connection = await self._get_connection()
            result = await asyncio.wait_for(
                cast(
                    Awaitable[Any],
                    connection.eval(  # type: ignore[UnknownMemberType]
                        RELEASE_KEY_LUA,
                        1,
                        key,
                        execution_id or "",
                    ),
                ),
                timeout=5,
            )
            return bool(result == 1)
        except Exception as exc:
            logger.warning("Failed to release idempotency key %s: %s", key, exc)
            return False


idempotency_service = IdempotencyService()


@asynccontextmanager
async def hold_reservation(
    reservation: "IdempotencyReservation | None",
) -> AsyncIterator[None]:
    """Hold an idempotency reservation for the duration of an admission."""
    if reservation is None:
        yield
        return

    async with reservation:
        yield


async def mark_completed_or_retain(
    service: IdempotencyService,
    *,
    key: str,
    execution_id: str,
    fingerprint: str,
    created_at: str,
) -> None:
    """Record completion after acceptance without ever weakening the key.

    Once the execution is published it is accepted: a tracking failure must not
    surface as an error to the caller. One atomic write either completes the
    entry or recreates it as completed if it lapsed, so the accepted execution
    always stays replayable and is never left blocking retries as `IN_PROGRESS`.
    """
    try:
        recorded = await service.complete_or_retain(
            key=key,
            execution_id=execution_id,
            fingerprint=fingerprint,
            created_at=created_at,
        )
        if recorded:
            return

        logger.warning(
            "Idempotency key %s was taken by another request while execution %s "
            "was being accepted; nothing could be recorded for it",
            key,
            execution_id,
        )
    except Exception:
        # The execution is already accepted and published; nothing here may
        # change the caller's outcome.
        logger.exception(
            "Idempotency key %s: unable to track the accepted execution %s",
            key,
            execution_id,
        )


class IdempotencyReservation:
    """Keeps an idempotency reservation alive for the duration of an admission.

    Admission covers file upload, database work and stream publication, which
    can outlast the short lock TTL. Renewing in the background keeps the key
    reserved, and `publish` fences the stream write on ownership inside Redis, so
    a reservation that was lost can never be published as a duplicate execution.
    """

    def __init__(
        self,
        service: IdempotencyService,
        *,
        key: str,
        execution_id: str,
        lock_ttl_seconds: int | None = None,
        renewal_interval_seconds: float | None = None,
    ) -> None:
        self._service = service
        self._key = key
        self._execution_id = execution_id
        self._lock_ttl_seconds = (
            lock_ttl_seconds or redis_settings.IDEMPOTENCY_LOCK_TTL_SECONDS
        )
        self._renewal_interval_seconds = renewal_interval_seconds or max(
            1.0, self._lock_ttl_seconds / 3
        )
        self._renewal_task: asyncio.Task[None] | None = None
        self._lost = False

    @property
    def is_lost(self) -> bool:
        return self._lost

    async def __aenter__(self) -> "IdempotencyReservation":
        self._renewal_task = asyncio.create_task(self._renew_until_closed())
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        task = self._renewal_task
        self._renewal_task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _renew_until_closed(self) -> None:
        while True:
            await asyncio.sleep(self._renewal_interval_seconds)
            renewed = await self._service.renew(
                key=self._key,
                execution_id=self._execution_id,
                lock_ttl_seconds=self._lock_ttl_seconds,
            )
            if not renewed:
                self._lost = True
                return

    async def publish(self, publisher: Any, message: Any) -> str:
        """Publish the execution only while this request still owns the key.

        Ownership, capacity admission and the stream write happen in one Redis
        script. Re-checking ownership separately is not enough: the publisher
        awaits its connection in between, and a stale request would then publish
        a second execution after another one had taken the key.
        """
        if self._lost:
            raise IdempotencyReservationLostException(execution_id=self._execution_id)

        try:
            message_id = await publisher.publish_message_fenced(
                message,
                reservation_key=self._key,
                reservation_execution_id=self._execution_id,
                reservation_ttl_seconds=redis_settings.IDEMPOTENCY_KEY_TTL_SECONDS,
            )
        except ReservationLostError as exc:
            self._lost = True
            raise IdempotencyReservationLostException(
                execution_id=self._execution_id
            ) from exc
        except PublicationOutcomeUnknownError:
            # The reply was lost: Redis may or may not have queued the work.
            # Accepting blindly marks an unscheduled execution as accepted;
            # failing blindly invites a duplicate. Ask the stream which it is.
            if await publisher.execution_is_queued(self._execution_id):
                logger.warning(
                    "Execution %s: publication reply was lost but the message is "
                    "on the stream; accepted",
                    self._execution_id,
                )
                return ""
            raise
        return message_id
