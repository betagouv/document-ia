import logging
from typing import cast

from fastapi import Depends, Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from document_ia_api.api.auth import get_api_key
from document_ia_api.api.exceptions.rate_limit_exception import RateLimitException
from document_ia_api.infra.redis_service import redis_service
from document_ia_api.schemas.rate_limiting import RateLimitInfo

logger = logging.getLogger(__name__)


async def check_rate_limit(
    request: Request, api_key: str = Depends(get_api_key)
) -> RateLimitInfo:
    """
    Rate limiting dependency that checks if the API key has exceeded rate limits.

    Args:
        request: FastAPI request object
        api_key: The authenticated API key (automatically validated)

    Returns:
        RateLimitInfo containing rate limit information

    Raises:
        HTTPException: If rate limit is exceeded
    """
    is_allowed, rate_limit_info = await redis_service.check_rate_limit(api_key)

    # Store rate limit info in request state for middleware access
    request.state.rate_limit_info = rate_limit_info

    if not is_allowed:
        # TODO: sanitize the api key in the logging service
        logger.warning(f"Rate limit exceeded for API key {api_key[:8]}...")

        raise RateLimitException(
            detail={
                "error": "Rate limit exceeded",
                "message": "Too many requests. Please try again later.",
                "rate_limit_info": rate_limit_info.model_dump(),
            }
        )

    return rate_limit_info


# TODO: implement FastAPI decorator for rate limiting
# see: https://fastapi.tiangolo.com/tutorial/middleware/
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware ajoutant les en-têtes de rate limit à la réponse."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        if hasattr(request.state, "rate_limit_info") and request.state.rate_limit_info:
            rate_limit_info = cast(RateLimitInfo, request.state.rate_limit_info)
            response.headers["X-RateLimit-Remaining-Minute"] = str(
                rate_limit_info.remaining_minute
            )
            response.headers["X-RateLimit-Remaining-Daily"] = str(
                rate_limit_info.remaining_daily
            )
            response.headers["X-RateLimit-Reset-Minute"] = (
                rate_limit_info.reset_minute or ""
            )
            response.headers["X-RateLimit-Reset-Daily"] = (
                rate_limit_info.reset_daily or ""
            )
        return response


# Dependency that can be used in route decorators
rate_limit_dependency = Depends(check_rate_limit)
