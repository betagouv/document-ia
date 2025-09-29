from typing import Optional

from fastapi import Security, HTTPException, Header
from fastapi.security import APIKeyHeader

from document_ia_api.api.config import settings

# Security scheme for API Key authentication
security = APIKeyHeader(name="X-API-KEY")


def verify_api_key(api_key: str = Security(security)):
    if not settings.API_KEY:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "server_configuration_error",
                "message": "API_KEY not configured on server",
            },
        )

    if api_key != settings.API_KEY.get_secret_value():
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Invalid API key"},
        )

    return api_key


def get_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-KEY")):
    """Get API key from header without requiring authentication."""
    return x_api_key
