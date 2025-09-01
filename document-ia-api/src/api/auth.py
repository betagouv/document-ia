from fastapi import Security
from fastapi.security import APIKeyHeader
from .config import settings
from .exceptions.http_exceptions import UnauthorizedException, CustomException

# Security scheme for API Key authentication
security = APIKeyHeader(name="X-API-KEY")


def verify_api_key(api_key: str = Security(security)):
    if not settings.api_key:
        raise CustomException(detail="API_KEY not configured on server")

    if api_key != settings.api_key:
        raise UnauthorizedException

    return api_key
