from fastapi import APIRouter, Depends
import logging

from document_ia_api.api.contracts.common import APIStatusResponse
from document_ia_api.api.auth import verify_api_key
from document_ia_api.api.rate_limiting import check_rate_limit
from document_ia_api.schemas.rate_limiting import RateLimitInfo
from document_ia_api.api.config import settings
from document_ia_api.api.routes.v1 import router as v1_router

# Configure logging
logger = logging.getLogger(__name__)

# Create router for API endpoints with comprehensive metadata
router = APIRouter()
# Add v1 router
router.include_router(v1_router)


@router.get(
    "/test",
    response_model=APIStatusResponse,
    summary="Test route",
    description="Test route",
    responses={
        200: {
            "model": APIStatusResponse,
            "description": "Test route retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "message": "Document IA API is running",
                        "version": "1.0.0",
                        "timestamp": "2024-01-15T10:30:00.000Z",
                    }
                }
            },
        }
    },
    tags=["Test"],
)
async def get_api_status(
    api_key: str = Depends(verify_api_key),
    rate_limit_info: RateLimitInfo = Depends(check_rate_limit),
) -> APIStatusResponse:
    """
    Test route.

    This endpoint is a test route.

    **Authentication Required**: This endpoint requires a valid API key in the Authorization header.

    **Rate Limiting**: This endpoint is subject to rate limiting based on your API key.
    """
    logger.info("Test route requested", extra={"endpoint": "get_api_status"})

    return APIStatusResponse(
        status="success",
        message="Document IA API is running",
        version=settings.APP_VERSION,
    )
