"""Conservative delivery-level classification; no exception text inspection."""

from typing import Literal

import httpx
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from document_ia_infra.exception.openai_authentification_error import (
    OpenAIAuthentificationError,
)
from document_ia_infra.exception.s3_authentification_exception import (
    S3AuthentificationException,
)
from document_ia_infra.exception.retryable_exception import RetryableException


def classify_failure(error: Exception) -> Literal["temporary", "permanent", "internal"]:
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status in {408, 425, 429} or 500 <= status < 600:
            return "temporary"
        return "permanent" if 400 <= status < 500 else "internal"
    if isinstance(
        error, (OpenAIAuthentificationError, S3AuthentificationException, ValueError)
    ):
        return "permanent"
    if isinstance(
        error,
        (
            RetryableException,
            httpx.TransportError,
            TimeoutError,
            ConnectionError,
            RedisConnectionError,
            RedisTimeoutError,
        ),
    ):
        return "temporary"
    return "internal"
