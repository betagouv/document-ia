from abc import ABC
from datetime import datetime
from typing import Dict, Any, Optional, List, Generic, TypeVar, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_serializer, model_validator

from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.barcode import BarcodeVariant
from document_ia_schemas import SupportedDocumentType, resolve_extract_schema

T = TypeVar("T", bound=BaseModel)


class BaseEvent(BaseModel, ABC):
    """Base event class with common fields for all events."""

    event_id: UUID = Field(
        description="Unique identifier for this event", default_factory=uuid4
    )
    workflow_id: str = Field(description="Workflow identifier")
    execution_id: str = Field(description="Execution instance identifier")
    created_at: datetime = Field(description="Event timestamp")
    version: int = Field(description="Event version for optimistic locking")
    event_type: EventType = Field(description="Event type")


class WorkflowExecutionStartedEvent(BaseEvent):
    """Event triggered when workflow execution begins."""

    event_type: EventType = Field(
        default=EventType.WORKFLOW_EXECUTION_STARTED, description="Event type"
    )
    file_info: FileInfo = Field(description="Uploaded file information")
    metadata: Dict[str, Any] = Field(description="Execution metadata")


class WorkflowExecutionStepCompletedEvent(BaseEvent):
    """Event triggered for each workflow step completion."""

    event_type: EventType = Field(
        default=EventType.WORKFLOW_EXECUTION_STEP_COMPLETED, description="Event type"
    )
    step_name: str = Field(description="Name of the completed step")
    step_result: Dict[str, Any] = Field(description="Result data from the step")
    execution_time_ms: int = Field(description="Step execution time in milliseconds")
    output_data: Optional[Dict[str, Any]] = Field(
        default=None, description="Step output data"
    )


class DocumentExtraction(BaseModel, Generic[T]):
    title: str
    type: SupportedDocumentType
    properties: T = Field(description="Document properties")

    @model_validator(mode="before")
    @classmethod
    def _coerce_properties_from_type(cls, data: Any) -> Any:
        """If properties is a dict, use `type` to instantiate the proper Pydantic model.

        This preserves the generic usage while ensuring round-trip (de)serialization.
        """
        try:
            if isinstance(data, dict):
                dict_data = cast(dict[str, Any], data)
                props_raw = dict_data.get("properties")
                doc_type_raw = dict_data.get("type")
                if isinstance(props_raw, dict) and isinstance(
                    doc_type_raw, (str, SupportedDocumentType)
                ):
                    props = cast(dict[str, Any], props_raw)
                    # normalize doc_type to string
                    doc_type_str: str = (
                        doc_type_raw.value
                        if isinstance(doc_type_raw, SupportedDocumentType)
                        else doc_type_raw
                    )
                    schema_cls = resolve_extract_schema(doc_type_str)
                    model_cls = getattr(schema_cls, "document_model", None)
                    if model_cls is not None:
                        # Replace raw dict with a concrete BaseModel instance
                        return cast(
                            Any, {**dict_data, "properties": model_cls(**props)}
                        )
        except Exception:
            # Fail-soft: keep original data if anything goes wrong
            return cast(Any, data)
        return cast(Any, data)

    @field_serializer("properties")
    def _serialize_properties(self, value: BaseModel) -> Any:
        # Render nested Pydantic model as dict (keep aliases, drop None)
        return value.model_dump(by_alias=True, exclude_none=True)


class DocumentClassification(BaseModel):
    explanation: str
    document_type: SupportedDocumentType
    confidence: float


class CompletedEventResult(BaseModel):
    extraction: Optional[DocumentExtraction[BaseModel]] = Field(
        default=None, description="Extraction result"
    )
    classification: Optional[DocumentClassification] = Field(
        default=None, description="Classification result"
    )
    # Preserve subclass fields by using a discriminated union on 'type'
    barcodes: List[BarcodeVariant] = Field(
        default=[], description="List of barcodes extracted from the document"
    )


class WorkflowExecutionCompletedEvent(BaseEvent):
    """Event triggered when entire workflow completes successfully."""

    event_type: EventType = Field(
        default=EventType.WORKFLOW_EXECUTION_COMPLETED, description="Event type"
    )
    final_result: CompletedEventResult = Field(description="Final workflow result")
    total_processing_time_ms: int = Field(
        description="Total processing time in milliseconds"
    )
    output_summary: Dict[str, Any] = Field(description="Summary of all outputs")
    steps_completed: int = Field(description="Number of steps completed")
    workflow_metadata: Optional[List[Any]] = Field(
        default=None, description="Workflow metadata"
    )


class WorkflowExecutionFailedEvent(BaseEvent):
    """Event triggered when processing fails."""

    event_type: EventType = Field(
        default=EventType.WORKFLOW_EXECUTION_FAILED, description="Event type"
    )
    error_type: str = Field(description="Type of error that occurred")
    error_message: str = Field(description="Detailed error message")
    failed_step: Optional[str] = Field(
        default=None, description="Step where failure occurred"
    )
    retry_count: int = Field(default=0, description="Number of retry attempts")


class EventStoreRecord(BaseModel):
    """Schema for event store database record."""

    id: UUID = Field(description="Primary key")
    workflow_id: str = Field(description="Workflow identifier")
    execution_id: str = Field(description="Execution instance identifier")
    created_at: datetime = Field(description="Event timestamp")
    event_type: EventType = Field(description="Type of event")
    event: BaseEvent = Field(description="Event payload as JSON")


class EventStream(BaseModel):
    """Schema for event stream response."""

    execution_id: str = Field(description="Execution instance identifier")
    workflow_id: str = Field(description="Workflow identifier")
    events: List[EventStoreRecord] = Field(description="List of events in the stream")
    total_events: int = Field(description="Total number of events")
    first_event_at: Optional[datetime] = Field(
        default=None, description="Timestamp of first event"
    )
    last_event_at: Optional[datetime] = Field(
        default=None, description="Timestamp of last event"
    )
