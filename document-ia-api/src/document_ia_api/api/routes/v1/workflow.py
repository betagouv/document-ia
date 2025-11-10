import logging
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.api.auth import verify_api_key, get_current_organization
from document_ia_api.api.contracts.error.errors import ProblemDetail
from document_ia_api.api.contracts.workflow import (
    WorkflowExecuteResponse,
)
from document_ia_api.api.middleware.rate_limiting_middleware import check_rate_limit
from document_ia_api.application.services.workflow_service import WorkflowService
from document_ia_api.schemas.rate_limiting import RateLimitInfo
from document_ia_infra.data.database import database_manager
from document_ia_infra.data.organization.dto.organization_dto import OrganizationDTO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows")


@router.post(
    "/{workflow_id}/execute",
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
                                "s3_key": "uploads/2024/01/15/document.pdf",
                                "size": 1024000,
                                "content_type": "application/pdf",
                                "uploaded_at": "2024-01-15T10:29:40.000Z",
                                "presigned_url": "https://minio.local/presigned/abc123",
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
            "model": ProblemDetail,
            "description": "Bad Request (ProblemDetail) — file validation error or bad input",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Bad Request",
                        "status": 400,
                        "code": "http.validation_error",
                        "instance": "/api/v1/workflows/{workflow_id}/execute",
                        "errors": {
                            "error": "file_validation_error",
                            "message": "Invalid file format. Supported formats: PDF, JPG, PNG",
                            "file_info": {
                                "filename": "document.txt",
                                "size": 1024,
                                "content_type": "text/plain",
                            },
                        },
                    }
                }
            },
        },
        401: {
            "model": ProblemDetail,
            "description": "Unauthorized (ProblemDetail) — missing or invalid API key",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Unauthorized",
                        "status": 401,
                        "code": "http.unauthorized",
                        "detail": "Unauthorized",
                        "instance": "/api/v1/workflows/{workflow_id}/execute",
                    }
                }
            },
        },
        422: {
            "model": ProblemDetail,
            "description": "Validation failed (ProblemDetail) — request schema validation errors",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Validation failed",
                        "status": 422,
                        "code": "validation.failed",
                        "instance": "/api/v1/workflows/{workflow_id}/execute",
                        "errors": {
                            "__root__": [
                                {
                                    "loc": ["path", "workflow_id"],
                                    "msg": "field required",
                                    "type": "value_error.missing",
                                },
                                {
                                    "loc": ["body", "file"],
                                    "msg": "field required",
                                    "type": "value_error.missing",
                                },
                                {
                                    "loc": ["body", "metadata"],
                                    "msg": "field required",
                                    "type": "value_error.missing",
                                },
                            ]
                        },
                    }
                }
            },
        },
        429: {
            "model": ProblemDetail,
            "description": "Too Many Requests (ProblemDetail) — rate limit exceeded",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Too Many Requests",
                        "status": 429,
                        "code": "http.rate_limited",
                        "detail": "Rate limit exceeded. Please try again later.",
                        "instance": "/api/v1/workflows/{workflow_id}/execute",
                    }
                }
            },
        },
        500: {
            "model": ProblemDetail,
            "description": "Internal Server Error (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Internal Server Error",
                        "status": 500,
                        "code": "internal.error",
                        "detail": "An unexpected error occurred while executing the workflow.",
                        "instance": "/api/v1/workflows/{workflow_id}/execute",
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
    ),
    metadata: Optional[str] = Form(
        default=None, description="JSON string containing metadata object"
    ),
    api_key: str = Depends(verify_api_key),
    current_org: OrganizationDTO = Depends(get_current_organization),
    rate_limit_info: RateLimitInfo = Depends(check_rate_limit),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
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

    try:
        # Create workflow service instance with database session
        workflow_service = WorkflowService(db_session)

        # Execute workflow using the service
        result = await workflow_service.execute_workflow(
            organization_id=current_org.id,
            workflow_id=workflow_id.strip(),
            file=file,
            metadata_json=metadata,
        )

        # Commit the database session to persist all changes (including events)
        await db_session.commit()

        logger.info(
            "Workflow execution started successfully",
            extra={
                "endpoint": "execute_workflow",
                "workflow_id": workflow_id,
                "execution_id": result.execution_id,
            },
        )

        return WorkflowExecuteResponse(
            status="success",
            data=result,
            message="Workflow execution started successfully",
        )

    except Exception as e:
        # Rollback the database session on any error
        await db_session.rollback()
        logger.error(f"Workflow execution failed: {e}")
        raise
