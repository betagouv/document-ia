import logging
from datetime import datetime

from fastapi import APIRouter
from fastapi import HTTPException, status

from document_ia_api.api.config import settings
from document_ia_api.api.contracts.common import HealthCheckResponse
from document_ia_api.infra.database_service import database_service
from document_ia_api.infra.redis_service import redis_service
from document_ia_api.infra.s3_service import s3_service
from document_ia_api.infra.schemas import (
    S3HealthStatus,
    RedisHealthStatus,
    DatabaseHealthStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="Health Check",
    description="Check the health status of the Document IA API service",
    responses={
        200: {
            "model": HealthCheckResponse,
            "description": "Service is healthy",
            "content": {
                "application/json": {
                    "example": {
                        "status": "healthy",
                        "timestamp": "2024-01-15T10:30:00.000Z",
                        "service": "Document IA API",
                        "version": "1.0.0",
                        "s3": {
                            "connected": True,
                            "credentials_valid": True,
                            "bucket_exists": True,
                            "is_healthy": True,
                            "errors": [],
                        },
                        "redis": {
                            "connected": True,
                            "is_healthy": True,
                            "errors": [],
                        },
                        "database": {
                            "connected": True,
                            "is_healthy": True,
                            "errors": [],
                        },
                    }
                }
            },
        },
        503: {
            "model": HealthCheckResponse,
            "description": "Service is unhealthy",
            "content": {
                "application/json": {
                    "example": {
                        "status": "unhealthy",
                        "timestamp": "2024-01-15T10:30:00.000Z",
                        "service": "Document IA API",
                        "version": "1.0.0",
                        "s3": {
                            "connected": False,
                            "credentials_valid": False,
                            "bucket_exists": False,
                            "is_healthy": False,
                            "errors": ["S3 connection failed"],
                        },
                        "redis": {
                            "connected": False,
                            "is_healthy": False,
                            "errors": ["Redis connection failed"],
                        },
                        "database": {
                            "connected": False,
                            "is_healthy": False,
                            "errors": ["Database connection failed"],
                        },
                    }
                }
            },
        },
    },
    tags=["Health"],
)
async def health_check() -> HealthCheckResponse:
    """
    Health check endpoint for monitoring and load balancer health checks.

    This endpoint is designed for monitoring systems and load balancers to check
    the health status of the Document IA API service. It performs comprehensive
    health checks including S3 and Redis connectivity validation.

    **No Authentication Required**: This endpoint is publicly accessible for monitoring.

    **Health Status Levels**:
    - `healthy`: All systems operational (HTTP 200)
    - `unhealthy`: Critical dependencies are unavailable (HTTP 503)
    """
    logger.debug("Health check requested", extra={"endpoint": "health_check"})

    try:
        # Perform S3 connectivity check
        s3_connectivity = await s3_service.check_connectivity()

        # Perform Redis connectivity check
        redis_connectivity = await redis_service.check_connectivity()

        # Perform Database connectivity check
        database_connectivity = await database_service.check_database_connectivity()

        # Determine overall health status based on service health flags
        if (
            s3_connectivity.is_healthy
            and redis_connectivity.is_healthy
            and database_connectivity.is_healthy
        ):
            overall_status = "healthy"
        else:
            overall_status = "unhealthy"

        # Create S3 health status object
        s3_health = S3HealthStatus.from_s3_connectivity_status(s3_connectivity)

        # Create Redis health status object
        redis_health = RedisHealthStatus.from_redis_connectivity_status(
            redis_connectivity
        )

        # Create Database health status object
        database_health = DatabaseHealthStatus.from_database_connectivity_status(
            database_connectivity
        )

        # Return healthy response (HTTP 200)
        if overall_status == "healthy":
            return HealthCheckResponse(
                status=overall_status,
                timestamp=datetime.now().isoformat(),
                service="Document IA API",
                version=settings.APP_VERSION,
                s3=s3_health,
                redis=redis_health,
                database=database_health,
            )

        # Raise exception for unhealthy status (HTTP 503)
        # TODO: return error details
        else:
            logger.warning(
                f"Service unhealthy - S3: {s3_connectivity.is_healthy}, Redis: {redis_connectivity.is_healthy}, Database: {database_connectivity.is_healthy}",
                extra={"endpoint": "health_check"},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service is currently unavailable - one or more dependencies are unhealthy",
            )

    except HTTPException:
        # Re-raise HTTP exceptions (like 503 above)
        raise
    except Exception as e:
        logger.error(f"Health check failed: {e}", extra={"endpoint": "health_check"})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal Server Error - Health check failed with error: {e}",
        )
