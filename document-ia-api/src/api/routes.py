from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from datetime import datetime
import logging

from api.auth import verify_api_key
from api.rate_limiting import check_rate_limit
from schemas.rate_limiting import RateLimitInfo
from api.contracts.workflow import WorkflowExecuteResponse, WorkflowErrorResponse
from api.contracts.common import (
    APIStatusResponse,
    HealthCheckResponse,
    S3HealthStatus,
    RedisHealthStatus,
)
from application.services.workflow_service import workflow_service
from api.config import settings
from infra.s3_service import s3_service
from infra.redis_service import redis_service

# Configure logging
logger = logging.getLogger(__name__)

# Create router for API endpoints with comprehensive metadata
router = APIRouter()


@router.get(
    "/v1/",
    response_model=APIStatusResponse,
    summary="Get API Status",
    description="Retrieve the current status and version information of the Document IA API",
    responses={
        200: {
            "model": APIStatusResponse,
            "description": "API status retrieved successfully",
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
    tags=["Status"],
)
async def get_api_status(
    api_key: str = Depends(verify_api_key),
    rate_limit_info: RateLimitInfo = Depends(check_rate_limit),
) -> APIStatusResponse:
    """
    Get API status and information.

    This endpoint provides information about the current status of the Document IA API,
    including version information and operational status.

    **Authentication Required**: This endpoint requires a valid API key in the Authorization header.

    **Rate Limiting**: This endpoint is subject to rate limiting based on your API key.
    """
    logger.info("API status requested", extra={"endpoint": "get_api_status"})

    return APIStatusResponse(
        status="success",
        message="Document IA API is running",
        version=settings.APP_VERSION,
    )


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

        # Determine overall health status based on service health flags
        if s3_connectivity["is_healthy"] and redis_connectivity["is_healthy"]:
            overall_status = "healthy"
        else:
            overall_status = "unhealthy"

        # Create S3 health status object
        s3_health = S3HealthStatus(
            connected=s3_connectivity["connected"],
            credentials_valid=s3_connectivity["credentials_valid"],
            bucket_exists=s3_connectivity["bucket_exists"],
            is_healthy=s3_connectivity["is_healthy"],
            errors=s3_connectivity["errors"],
        )

        # Create Redis health status object
        redis_health = RedisHealthStatus(
            connected=redis_connectivity["connected"],
            is_healthy=redis_connectivity["is_healthy"],
            errors=redis_connectivity["errors"],
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
            )

        # Raise exception for unhealthy status (HTTP 503)
        else:
            logger.warning(
                f"Service unhealthy - S3: {s3_connectivity['is_healthy']}, Redis: {redis_connectivity['is_healthy']}",
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


@router.post(
    "/v1/workflows/{workflow_id}/execute",
    response_model=WorkflowExecuteResponse,
    summary="Execute Workflow",
    description="Execute a document processing workflow with file upload and metadata",
    responses={
        200: {
            "model": WorkflowExecuteResponse,
            "description": "Workflow execution started successfully",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "data": {
                            "execution_id": "exec_123456789",
                            "workflow_id": "workflow_001",
                            "status": "processing",
                            "created_at": "2024-01-15T10:30:00.000Z",
                            "file_info": {
                                "filename": "document.pdf",
                                "size": 1024000,
                                "content_type": "application/pdf",
                            },
                            "metadata": {"source": "email", "priority": "high"},
                        },
                        "message": "Workflow execution started successfully",
                        "timestamp": "2024-01-15T10:30:00.000Z",
                    }
                }
            },
        },
        400: {
            "model": WorkflowErrorResponse,
            "description": "Invalid request data or file validation error",
            "content": {
                "application/json": {
                    "example": {
                        "status": "error",
                        "error": "ValidationError",
                        "message": "Invalid file format. Supported formats: PDF, JPG, PNG",
                        "details": {"supported_formats": ["pdf", "jpg", "png"]},
                        "timestamp": "2024-01-15T10:30:00.000Z",
                    }
                }
            },
        },
    },
    tags=["Workflows"],
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "file": {
                                "type": "string",
                                "format": "binary",
                                "description": "Document file to process (PDF, JPG, PNG, max 25MB)",
                            },
                            "metadata": {
                                "type": "string",
                                "description": "JSON string containing metadata object",
                                "examples": [
                                    '{"source": "email", "priority": "high", "tags": ["invoice", "urgent"]}'
                                ],
                            },
                        },
                        "required": ["file", "metadata"],
                    }
                }
            }
        }
    },
)
async def execute_workflow(
    workflow_id: str,
    file: UploadFile = File(
        ...,
        description="Document file to process (PDF, JPG, PNG, max 25MB)",
        media_type=["application/pdf", "image/jpeg", "image/png"],
    ),
    metadata: str = Form(..., description="JSON string containing metadata object"),
    api_key: str = Depends(verify_api_key),
    rate_limit_info: RateLimitInfo = Depends(check_rate_limit),
) -> WorkflowExecuteResponse:
    """
    Execute a document processing workflow with file upload and metadata.

    This endpoint processes documents through predefined workflows, supporting various
    file formats and custom metadata. The workflow execution is asynchronous and returns
    immediately with an execution ID for tracking.

    **Authentication Required**: This endpoint requires a valid API key in the Authorization header.

    **Rate Limiting**: This endpoint is subject to rate limiting based on your API key.

    **File Requirements**:
    - Supported formats: PDF, JPG, PNG
    - Maximum file size: 25MB
    - File must be valid and readable

    **Metadata Format**:
    The metadata parameter should be a JSON string containing key-value pairs
    that will be passed to the workflow for processing context.
    """
    logger.info(
        "Workflow execution requested",
        extra={
            "endpoint": "execute_workflow",
            "workflow_id": workflow_id,
            "content_type": file.content_type,
            "file_size": file.size if hasattr(file, "size") else "unknown",
        },
    )

    # Execute workflow using the service
    result = await workflow_service.execute_workflow(
        workflow_id=workflow_id.strip(), file=file, metadata_json=metadata
    )

    logger.info(
        "Workflow execution started successfully",
        extra={
            "endpoint": "execute_workflow",
            "workflow_id": workflow_id,
            "execution_id": result.execution_id,
        },
    )

    return WorkflowExecuteResponse(
        status="success", data=result, message="Workflow execution started successfully"
    )
