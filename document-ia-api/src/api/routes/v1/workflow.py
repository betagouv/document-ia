from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import verify_api_key
from api.rate_limiting import check_rate_limit
from schemas.rate_limiting import RateLimitInfo
from api.contracts.workflow import WorkflowExecuteResponse, WorkflowErrorResponse
from application.services.workflow_service import WorkflowService
from infra.database.database import async_get_db

import logging

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
        422: {
            "description": "Erreur de validation (schéma Pydantic) – champs manquants ou invalides",
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
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
    metadata: str = Form(..., description="JSON string containing metadata object"),
    api_key: str = Depends(verify_api_key),
    rate_limit_info: RateLimitInfo = Depends(check_rate_limit),
    db_session: AsyncSession = Depends(async_get_db),
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
            workflow_id=workflow_id.strip(), file=file, metadata_json=metadata
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
