from fastapi import Security
from fastapi.security import APIKeyHeader
from .config import settings
from .exceptions.http_exceptions import UnauthorizedException, CustomException

# Security scheme for API Key authentication
security = APIKeyHeader(name="X-API-KEY")


def verify_api_key(api_key: str = Security(security)):
    if not settings.API_KEY:
        raise CustomException(detail="API_KEY not configured on server")

    if api_key != settings.API_KEY:
        raise UnauthorizedException

    return api_key


def get_api_key(api_key: str = Security(security)):
    return api_key
