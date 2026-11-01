import logging
from typing import Any, Optional

from fastapi import HTTPException

from document_ia_api.api.contracts.execution.failed import (
    ExecutionFailedModel,
    ExecutionFailedData,
)
from document_ia_api.api.contracts.execution.result import (
    ClassificationResult,
    ExtractionResult,
)
from document_ia_api.api.contracts.execution.started import (
    ExecutionStartedModel,
    ExecutionStartedData,
    S3FileInfo,
)
from document_ia_api.api.contracts.execution.success import (
    ExecutionSuccessModel,
    SuccessResult,
    SuccessData,
)
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_infra.core.model.typed_generic_model import GenericProperty
from document_ia_infra.data.document.schema.document_extraction import (
    DocumentExtraction,
)
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.mappers.event_mapper import (
    decode_event_dto,
)
from document_ia_infra.data.event.schema.workflow.workflow_execution_completed_event import (
    WorkflowExecutionCompletedEvent,
)
from document_ia_infra.data.event.schema.workflow.workflow_execution_failed_event import (
    WorkflowExecutionFailedEvent,
)
from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import (
    WorkflowExecutionStartedEvent,
)
from document_ia_schemas import SupportedDocumentType

logger = logging.getLogger(__name__)


class ExecutionService:
    """Service for handling execution business logic."""

    def __init__(self):
        pass

    def get_event_model(
        self, event_dto: EventDTO, execution_id: str, is_debug_mode: bool
    ) -> ExecutionStartedModel | ExecutionSuccessModel | ExecutionFailedModel:
        if event_dto.event_type not in (
            EventType.WORKFLOW_EXECUTION_STARTED,
            EventType.WORKFLOW_EXECUTION_FAILED,
            EventType.WORKFLOW_EXECUTION_COMPLETED,
        ):
            raise HTTPException(status_code=400, detail="Event type not supported")

        event_data = decode_event_dto(event_dto)
        if isinstance(event_data, WorkflowExecutionStartedEvent):
            file_info: Optional[S3FileInfo] = None
            if event_data.s3_file_info is not None:
                file_info = S3FileInfo(
                    file_name=event_data.s3_file_info.filename,
                    content_type=event_data.s3_file_info.content_type,
                    presigned_url=event_data.s3_file_info.presigned_url,
                )
            return ExecutionStartedModel(
                id=execution_id,
                status=ExecutionStatus.STARTED,
                data=ExecutionStartedData(
                    created_at=event_dto.created_at,
                    s3_file_info=file_info,
                    file_url=event_data.file_url,
                ),
            )

        if isinstance(event_data, WorkflowExecutionFailedEvent):
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

        if isinstance(event_data, WorkflowExecutionCompletedEvent):
            return self._get_success_response(execution_id, event_data, is_debug_mode)

        raise HTTPException(status_code=400, detail="Event type not supported")

    def _get_success_response(
        self,
        execution_id: str,
        event_data: WorkflowExecutionCompletedEvent,
        is_debug_mode: bool,
    ):
        success_result = SuccessResult()

        if event_data.final_result.classification is not None:
            success_result.classification = ClassificationResult(
                confidence=event_data.final_result.classification.confidence,
                document_type=event_data.final_result.classification.document_type,
                explanation=event_data.final_result.classification.explanation,
            )

        if event_data.final_result.extraction is not None:
            if event_data.final_result.extraction.type == SupportedDocumentType.AUTRE:
                success_result.extraction = ExtractionResult(
                    type=event_data.final_result.extraction.type,
                    properties=[],
                )
            else:
                success_result.extraction = self._convert_extraction_result(
                    event_data.final_result.extraction
                )

        success_result.barcodes = event_data.final_result.barcodes

        if is_debug_mode and event_data.workflow_metadata is not None:
            success_result.workflow_metadata = event_data.workflow_metadata

        success_data = SuccessData(
            total_processing_time_ms=event_data.total_processing_time_ms,
            result=success_result,
        )

        return ExecutionSuccessModel(
            id=execution_id, status=ExecutionStatus.SUCCESS, data=success_data
        )

    def _convert_extraction_result(
        self,
        extraction_data: DocumentExtraction[Any],
    ) -> ExtractionResult:
        """Project the already-decoded domain extraction into the API contract."""
        return ExtractionResult(
            type=extraction_data.type,
            properties=GenericProperty.convert_pydantic_model(
                extraction_data.properties
            ),
        )
