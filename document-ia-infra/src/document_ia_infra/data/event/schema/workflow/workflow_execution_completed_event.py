from typing import Dict, Any, Optional, List

from pydantic import Field, BaseModel

from document_ia_infra.data.document.schema.document_classification import (
    DocumentClassification,
)
from document_ia_infra.data.document.schema.document_extraction import (
    DocumentExtraction,
)
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.barcode import BarcodeVariant
from document_ia_infra.data.event.schema.event import BaseEvent


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
