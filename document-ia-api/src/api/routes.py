from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from datetime import datetime
import logging

from api.auth import verify_api_key
from api.rate_limiting import check_rate_limit
from schemas.rate_limiting import RateLimitInfo
from api.contracts.workflow import WorkflowExecuteResponse, WorkflowErrorResponse
from api.contracts.common import APIStatusResponse, HealthCheckResponse, ErrorResponse
from application.services.workflow_service import workflow_service
from api.config import settings

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
                        "uptime": "3600",
                    }
                }
            },
        },
        503: {"model": ErrorResponse, "description": "Service is unhealthy"},
    },
    tags=["Health"],
)
async def health_check() -> HealthCheckResponse:
    """
    Health check endpoint for monitoring and load balancer health checks.

    This endpoint is designed for monitoring systems and load balancers to check
    the health status of the Document IA API service. It does not require authentication
    and should respond quickly with minimal processing.

    **No Authentication Required**: This endpoint is publicly accessible for monitoring.
    """
    logger.debug("Health check requested", extra={"endpoint": "health_check"})

    try:
        # Here you could add additional health checks like:
        # - Database connectivity
        # - Redis connectivity
        # - S3 connectivity
        # - External service dependencies

        return HealthCheckResponse(
            status="healthy",
            timestamp=datetime.now().isoformat(),
            service="Document IA API",
            version=settings.APP_VERSION,
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}", extra={"endpoint": "health_check"})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is currently unavailable",
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
                            "estimated_completion": "2024-01-15T10:35:00.000Z",
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
                                "example": '{"source": "email", "priority": "high", "tags": ["invoice", "urgent"]}',
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
    metadata: str = Form(
        ...,
        description="JSON string containing metadata object",
        examples='[{"source": "email", "priority": "high", "tags": ["invoice", "urgent"]}]',
    ),
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
