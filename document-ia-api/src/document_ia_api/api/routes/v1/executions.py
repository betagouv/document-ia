import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.api.auth import verify_api_key, get_current_organization
from document_ia_api.api.contracts.error.errors import ProblemDetail
from document_ia_api.api.contracts.execution.failed import (
    ExecutionFailedModel,
)
from document_ia_api.api.contracts.execution.response import ExecutionResponse
from document_ia_api.api.contracts.execution.started import (
    ExecutionStartedModel,
)
from document_ia_api.api.contracts.execution.success import (
    ExecutionSuccessModel,
)
from document_ia_api.api.exceptions.entity_not_found_exception import (
    HttpEntityNotFoundException,
)
from document_ia_api.application.services.execution_service import ExecutionService
from document_ia_infra.data.database import database_manager
from document_ia_infra.data.organization.dto.organization_dto import OrganizationDTO
from document_ia_infra.data.workflow.repository.worflow import workflow_repository
from document_ia_infra.exception.entity_not_found_exception import (
    EntityNotFoundException,
)
from document_ia_infra.service.event_store_service import EventStoreService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/executions")


@router.get(
    "/{execution_id}",
    summary="Get Execution details",
    description="Retrieve execution details by execution ID. Response is discriminated by 'status' (STARTED | SUCCESS | FAILED).",
    response_model=ExecutionResponse,
    response_model_exclude_none=True,
    responses={
        200: {
            "description": "Execution details retrieved successfully",
            "content": {
                "application/json": {
                    "examples": {
                        "started": {
                            "summary": "Execution started",
                            "value": {
                                "id": "exec_123",
                                "status": "STARTED",
                                "data": {
                                    "created_at": "2024-01-15T10:30:00Z",
                                    "file_name": "document.pdf",
                                    "content_type": "application/pdf",
                                    "presigned_url": "https://minio.local/presigned/abc123",
                                },
                            },
                        },
                        "success": {
                            "summary": "Completed execution (success)",
                            "value": {
                                "id": "exec_123",
                                "status": "SUCCESS",
                                "data": {
                                    "total_processing_time_ms": 1200,
                                    "result": {
                                        "classification": {
                                            "document_type": "CNI",
                                            "confidence": 0.9,
                                            "explanation": "Detected as CNI",
                                        },
                                        "extraction": {
                                            "type": "CNI",
                                            "properties": [
                                                {
                                                    "name": "first_name",
                                                    "value": "Alice",
                                                    "type": "str",
                                                }
                                            ],
                                        },
                                        "barcodes": [],
                                        "workflow_metadata": [
                                            {"step": "ocr", "execution_time": 120.5}
                                        ],
                                    },
                                },
                            },
                        },
                        "failed": {
                            "summary": "Execution failed",
                            "value": {
                                "id": "exec_123",
                                "status": "FAILED",
                                "data": {
                                    "error_type": "RuntimeError",
                                    "failed_step": "classification",
                                    "retry_count": 1,
                                    "workflow_id": "wf_001",
                                    "error_message": "LLM timeout",
                                },
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
                        "instance": "/api/v1/executions/{execution_id}",
                    }
                }
            },
        },
        404: {
            "model": ProblemDetail,
            "description": "Execution not found (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Not Found",
                        "status": 404,
                        "code": "http.not_found",
                        "instance": "/api/v1/executions/{execution_id}",
                        "errors": {
                            "entity": "Execution",
                            "id": "exec_123",
                            "message": "Execution not found",
                        },
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
                        "instance": "/api/v1/executions/{execution_id}",
                    }
                }
            },
        },
    },
    tags=["Executions"],
)
async def get_execution(
    execution_id: str,
    api_key: str = Depends(verify_api_key),
    organization: OrganizationDTO = Depends(get_current_organization),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
    is_debug_mode: bool = Query(False),
) -> ExecutionStartedModel | ExecutionSuccessModel | ExecutionFailedModel:
    logger.info(
        "Execution details requested",
        extra={"endpoint": "get_execution", "execution_id": execution_id},
    )

    event_store_service = EventStoreService(db_session)
    execution_service = ExecutionService(db_session)
    try:
        last_event = await event_store_service.get_last_event_for_execution_id(
            execution_id
        )
        if last_event.organization_id != organization.id:
            raise HTTPException(
                status_code=401, detail="Unauthorized access to execution"
            )
        workflow = await workflow_repository.get_workflow_by_id(last_event.workflow_id)
        if workflow is None:
            raise EntityNotFoundException("Workflow", last_event.workflow_id)

        return execution_service.get_event_model(
            last_event, execution_id, is_debug_mode
        )

    except EntityNotFoundException as e:
        raise HttpEntityNotFoundException(
            entity_name=e.entity_name, entity_id=e.entity_id
        )
    except HttpEntityNotFoundException as e:
        raise e
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(
            "Error retrieving execution events",
            extra={
                "endpoint": "get_execution",
                "execution_id": execution_id,
                "error": str(e),
            },
        )
        raise HTTPException(status_code=500, detail=str(e))
