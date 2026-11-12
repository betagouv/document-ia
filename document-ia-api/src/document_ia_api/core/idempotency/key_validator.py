from document_ia_api.core.idempotency.exceptions import (
    InvalidIdempotencyKeyException,
)


def validate_idempotency_key(key: str | None) -> None:
    """Validate that the idempotency key matches requirements.

    Requirements:
    - Optional: if None, validation succeeds.
    - Must be a printable ASCII string (characters 32 to 126 inclusive).
    - Length must be between 1 and 256 characters inclusive.

    Raises:
        InvalidIdempotencyKeyException: If the key format is invalid.
    """
    if key is None:
        return

    if not (1 <= len(key) <= 256):
        raise InvalidIdempotencyKeyException(
            "Idempotency-Key header must be between 1 and 256 characters."
        )

    if not key.isascii() or not all(32 <= ord(c) <= 126 for c in key):
        raise InvalidIdempotencyKeyException(
            "Idempotency-Key header must be a printable ASCII string."
        )
