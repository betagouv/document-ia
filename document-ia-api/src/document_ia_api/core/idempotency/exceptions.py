from fastapi import HTTPException

from document_ia_infra.redis.redis_settings import redis_settings


class InvalidIdempotencyKeyException(HTTPException):
    def __init__(
        self,
        message: str = "Idempotency-Key header must be a printable ASCII string between 1 and 256 characters.",
    ) -> None:
        super().__init__(
            status_code=400,
            detail={
                "error": "invalid_idempotency_key",
                "message": message,
            },
        )


class IdempotencyConflictException(HTTPException):
    def __init__(
        self,
        message: str = "The idempotency key is already used with a different request payload.",
    ) -> None:
        super().__init__(
            status_code=409,
            detail={
                "error": "idempotency_conflict",
                "message": message,
            },
        )


class IdempotencyInProgressException(HTTPException):
    def __init__(
        self,
        execution_id: str,
        message: str = (
            "An execution with this idempotency key is currently being processed. "
            "You can query its status using the provided execution_id."
        ),
    ) -> None:
        super().__init__(
            status_code=409,
            detail={
                "error": "idempotency_in_progress",
                "execution_id": execution_id,
                "message": message,
            },
        )


class IdempotencyReservationLostException(HTTPException):
    """The reservation expired or was re-acquired before this request published.

    The request must not create its execution: the key now protects another
    caller, and publishing here would produce the duplicate the key exists to
    prevent. The error carries `Retry-After` so the client retries rather than
    treating the request as permanently refused.
    """

    def __init__(
        self,
        execution_id: str | None = None,
        message: str = (
            "The idempotency reservation was lost before the execution was "
            "scheduled. Retry the request."
        ),
    ) -> None:
        detail: dict[str, str] = {
            "error": "idempotency_reservation_lost",
            "message": message,
        }
        if execution_id is not None:
            # The started event is committed before publication, so the caller
            # can inspect the execution this request closed.
            detail["execution_id"] = execution_id

        super().__init__(
            status_code=503,
            detail=detail,
            headers={
                "Retry-After": str(redis_settings.PUBLISH_RETRY_AFTER_SECONDS),
            },
        )
