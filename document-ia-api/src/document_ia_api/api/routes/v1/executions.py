import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.api.auth import verify_api_key
from document_ia_api.api.contracts.api_error import ApiErrorResponse
from document_ia_api.api.contracts.execution.failed import (
    ExecutionFailedModel,
    ExecutionFailedData,
)
from document_ia_api.api.contracts.execution.response import ExecutionResponse
from document_ia_api.api.contracts.execution.result import (
    ClassificationResult,
    ExtractionResult,
)
from document_ia_api.api.contracts.execution.started import (
    ExecutionStartedModel,
    ExecutionStartedData,
)
from document_ia_api.api.contracts.execution.success import (
    ExecutionSuccessModel,
    ClassificationSuccessData,
    ExtractionSuccessData,
)
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_api.api.exceptions.entity_not_found_exception import (
    HttpEntityNotFoundException,
)
from document_ia_infra.data.database import database_manager
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.event import (
    WorkflowExecutionStartedEvent,
    WorkflowExecutionCompletedEvent,
    WorkflowExecutionFailedEvent,
)
from document_ia_infra.data.workflow.dto.workflow_dto import WorkflowDTO, WorkflowType
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
) -> ExecutionStartedModel | ExecutionSuccessModel | ExecutionFailedModel:
    logger.info(
        "Execution details requested",
        extra={"endpoint": "get_execution", "execution_id": execution_id},
    )

    event_store_service = EventStoreService(db_session)
    try:
        last_event = await event_store_service.get_last_event_for_execution_id(
            execution_id
        )
        workflow = await workflow_repository.get_workflow_by_id(last_event.workflow_id)
        if workflow is None:
            raise EntityNotFoundException("Workflow", last_event.workflow_id)

        if last_event.event_type == EventType.WORKFLOW_EXECUTION_STARTED:
            event_data = WorkflowExecutionStartedEvent(**last_event.event)
            return ExecutionStartedModel(
                id=execution_id,
                status=ExecutionStatus.STARTED,
                data=ExecutionStartedData(
                    created_at=last_event.created_at,
                    file_name=event_data.file_info.filename,
                    content_type=event_data.file_info.content_type,
                    presigned_url=event_data.file_info.presigned_url,
                ),
            )

        if last_event.event_type == EventType.WORKFLOW_EXECUTION_COMPLETED:
            return _get_success_response(execution_id, last_event, workflow)

        if last_event.event_type == EventType.WORKFLOW_EXECUTION_FAILED:
            event_data = WorkflowExecutionFailedEvent(**last_event.event)
            return ExecutionFailedModel(
                id=execution_id,
                status=ExecutionStatus.FAILED,
                data=ExecutionFailedData(
                    error_type=event_data.error_type,
                    failed_step=event_data.failed_step,
                    retry_count=event_data.retry_count,
                    workflow_id=event_data.workflow_id,
                    error_message=event_data.error_message,
                ),
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
    raise HTTPException(status_code=404, detail="Execution not found")


def _get_success_response(
    execution_id: str, last_event: EventDTO, workflow: WorkflowDTO
):
    event_data = WorkflowExecutionCompletedEvent(**last_event.event)
    if workflow.type == WorkflowType.CLASSIFICATION:
        return_data = ClassificationSuccessData(
            workflow_type=WorkflowType.CLASSIFICATION,
            total_processing_time_ms=event_data.total_processing_time_ms,
            result=ClassificationResult(
                confidence=event_data.final_result["confidence"],
                document_type=event_data.final_result["document_type"],
                explanation=event_data.final_result["explanation"],
            ),
            extracted_barcodes=event_data.final_result.get("barcode_data"),
        )
    elif workflow.type == WorkflowType.EXTRACTION:
        return_data = ExtractionSuccessData(
            workflow_type=WorkflowType.EXTRACTION,
            total_processing_time_ms=event_data.total_processing_time_ms,
            result=ExtractionResult(
                classification=ClassificationResult(
                    confidence=event_data.final_result["classification"]["confidence"],
                    document_type=event_data.final_result["classification"][
                        "document_type"
                    ],
                    explanation=event_data.final_result["classification"][
                        "explanation"
                    ],
                ),
                extracted_fields=event_data.final_result["extraction"],
            ),
            extracted_barcodes=event_data.final_result.get("barcode_data"),
        )
    else:
        raise ValueError(f"Unsupported workflow type: {workflow.type}")

    return ExecutionSuccessModel(
        id=execution_id, status=ExecutionStatus.SUCCESS, data=return_data
    )
