from typing import Any

from fastapi import HTTPException


class RateLimitException(HTTPException):
    def __init__(self, status_code: int = 429, detail: dict[str, Any] | None = None):
        super().__init__(status_code=status_code, detail=detail)
