from fastapi import HTTPException


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
