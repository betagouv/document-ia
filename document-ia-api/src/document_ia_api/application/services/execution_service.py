import logging
from typing import Any, Literal

from document_ia_infra.core.model.typed_generic_model import GenericProperty
from document_ia_schemas import resolve_extract_schema, BaseDocumentTypeSchema
from fastapi import HTTPException
from pydantic import BaseModel

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
)
from document_ia_api.api.contracts.execution.success import (
    ExecutionSuccessModel,
    SuccessResult,
    SuccessData,
)
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_infra.data.document.schema.document_extraction import (
    DocumentExtraction,
)
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.workflow.workflow_execution_completed_event import (
    WorkflowExecutionCompletedEvent,
)
from document_ia_infra.data.event.schema.workflow.workflow_execution_failed_event import (
    WorkflowExecutionFailedEvent,
)
from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import (
    WorkflowExecutionStartedEvent,
)

logger = logging.getLogger(__name__)


class ExecutionService:
    """Service for handling execution business logic."""

    def __init__(self):
        pass

    def get_event_model(
        self, event_dto: EventDTO, execution_id: str, is_debug_mode: bool
    ) -> ExecutionStartedModel | ExecutionSuccessModel | ExecutionFailedModel:
        if event_dto.event_type == EventType.WORKFLOW_EXECUTION_STARTED:
            event_data = WorkflowExecutionStartedEvent(**event_dto.event)
            return ExecutionStartedModel(
                id=execution_id,
                status=ExecutionStatus.STARTED,
                data=ExecutionStartedData(
                    created_at=event_dto.created_at,
                    file_name=event_data.file_info.filename,
                    content_type=event_data.file_info.content_type,
                    presigned_url=event_data.file_info.presigned_url,
                ),
            )

        if event_dto.event_type == EventType.WORKFLOW_EXECUTION_FAILED:
            event_data = WorkflowExecutionFailedEvent(**event_dto.event)
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

        if event_dto.event_type == EventType.WORKFLOW_EXECUTION_COMPLETED:
            return self._get_success_response(execution_id, event_dto, is_debug_mode)

        raise HTTPException(status_code=400, detail="Event type not supported")

    def _get_success_response(
        self, execution_id: str, last_event: EventDTO, is_debug_mode: bool
    ):
        event_data = WorkflowExecutionCompletedEvent(**last_event.event)

        success_result = SuccessResult()

        if event_data.final_result.classification is not None:
            success_result.classification = ClassificationResult(
                confidence=event_data.final_result.classification.confidence,
                document_type=event_data.final_result.classification.document_type,
                explanation=event_data.final_result.classification.explanation,
            )

        if event_data.final_result.extraction is not None:
            extraction_class = resolve_extract_schema(
                event_data.final_result.extraction.type.value
            )
            success_result.extraction = self._convert_extraction_result(
                event_data.final_result.extraction, extraction_class
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

    def _infer_value_type(
        self, value: Any
    ) -> Literal["string", "number", "boolean", "object"]:
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "number"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        return "object"

    def _convert_extraction_result(
        self,
        extraction_data: DocumentExtraction[Any],
        extraction_class: BaseDocumentTypeSchema[BaseModel],
    ) -> ExtractionResult:
        model_cls: type[BaseModel] = extraction_class.document_model

        # On récupère les propriétés brutes (souvent une instance Pydantic)
        props_raw: Any = extraction_data.properties

        # Si ce n'est pas déjà une instance de `model_cls`, on tente de l'instancier
        model_instance: BaseModel
        if isinstance(props_raw, BaseModel):
            model_instance = props_raw
        elif isinstance(props_raw, dict):
            model_instance = model_cls(**props_raw)
        else:
            model_instance = model_cls(**getattr(props_raw, "__dict__", {}))

        # Utilisation centrale de `GenericProperty`
        generic_properties: list[GenericProperty] = (
            GenericProperty.convert_pydantic_model(model_instance)
        )

        return ExtractionResult(
            type=extraction_data.type,
            properties=generic_properties,
        )
