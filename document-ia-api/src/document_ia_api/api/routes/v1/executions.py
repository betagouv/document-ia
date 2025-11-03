import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.api.auth import verify_api_key
from document_ia_api.api.contracts.api_error import ApiErrorResponse
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
    description="Retrieve execution details by execution ID. Response is discriminated by 'status' (PENDING | DONE).",
    response_model=ExecutionResponse,
    response_model_exclude_none=True,
    responses={
        200: {
            "description": "Execution details retrieved successfully",
            "content": {
                "application/json": {
                    "examples": {
                        "pending": {
                            "summary": "Pending execution",
                            "value": {
                                "id": "exec_123",
                                "status": "PENDING",
                                "data": {
                                    "created_at": "2024-01-15T10:30:00Z",
                                    "file_name": "sdkjfhsfjk",
                                    "file_type": "application/pdf",
                                    "presigned_url": "https://sdlkfjdskjf",
                                },
                            },
                        },
                        "done": {
                            "summary": "Completed execution",
                            "value": {
                                "id": "exec_123",
                                "status": "DONE",
                                "data": {
                                    "time_spent_ms": 1200,
                                    "result": {
                                        "document_type": "cni",
                                        "confidence": 0.9,
                                        "explanation": "blabla",
                                    },
                                },
                            },
                        },
                    }
                }
            },
        },
        404: {
            "model": ApiErrorResponse,
            "description": "Execution not found",
            "content": {
                "application/json": {
                    "example": {
                        "status": "error",
                        "error": "NotFound",
                        "message": "Execution not found",
                    }
                }
            },
        },
        500: {
            "model": ApiErrorResponse,
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "status": "error",
                        "error": "InternalServerError",
                        "message": "An unexpected error occurred",
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
