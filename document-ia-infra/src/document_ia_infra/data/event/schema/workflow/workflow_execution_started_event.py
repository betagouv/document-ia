from typing import Dict, Any, Optional

from pydantic import Field, BaseModel

from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.event import BaseEvent
from document_ia_infra.data.workflow.dto.workflow_dto import LLMModel
from document_ia_schemas import SupportedDocumentType


class ClassificationParameters(BaseModel):
    llm_model: Optional[LLMModel] = Field(
        default=None, description="LLM model for classification"
    )
    document_types: Optional[list[SupportedDocumentType]] = Field(
        default=None,
        description="Restrict classification to these document types. If not set, all supported types are used.",
    )


class ExtractionParameters(BaseModel):
    llm_model: Optional[LLMModel] = Field(
        default=None, description="LLM model for extraction"
    )
    document_type: Optional[SupportedDocumentType] = Field(
        default=None, description="Document type"
    )


class WorkflowExecutionStartedEvent(BaseEvent):
    """Event triggered when workflow execution begins."""

    event_type: EventType = Field(
        default=EventType.WORKFLOW_EXECUTION_STARTED, description="Event type"
    )
    s3_file_info: Optional[FileInfo] = Field(
        description="Uploaded file information", default=None
    )
    file_url: Optional[str] = Field(
        default=None, description="URL of the file to be processed"
    )
    metadata: Dict[str, Any] = Field(description="Execution metadata")
    classification_parameters: ClassificationParameters = Field(
        description="Classification parameters"
    )
    extraction_parameters: ExtractionParameters = Field(
        description="Extraction parameters"
    )
