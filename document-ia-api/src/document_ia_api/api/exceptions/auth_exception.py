from fastapi import HTTPException


class MissingApiKeyException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=401,
            detail="Missing API key",
            headers={"WWW-Authenticate": "APIKey"},
        )


class InvalidApiKeyException(HTTPException):
    def __init__(self, detail: str = "Invalid API key"):
        super().__init__(
            status_code=401,
            detail=detail,
            headers={"WWW-Authenticate": "APIKey"},
        )
