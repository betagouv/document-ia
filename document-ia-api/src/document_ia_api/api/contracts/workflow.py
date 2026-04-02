from datetime import datetime
from typing import Dict, Any, Optional

from document_ia_schemas import SupportedDocumentType
from pydantic import BaseModel, Field

from document_ia_api.schemas.workflow import WorkflowExecutionData
from document_ia_infra.data.workflow.dto.workflow_dto import LLMModel


class WorkflowClassificationParameterRequest(BaseModel):
    llm_model: Optional[LLMModel] = Field(
        default=None,
        description="LLM model to be used for classification override workflow parameter",
        alias="llm-model",
    )
    document_types: Optional[list[SupportedDocumentType]] = Field(
        default=None,
        description="Restrict classification to these document types. If not set, all supported types are used.",
        alias="document-types",
    )


class WorkflowExtractionParameterRequest(BaseModel):
    llm_model: Optional[LLMModel] = Field(
        default=None,
        description="LLM model to be used for extraction override workflow parameter",
        alias="llm-model",
    )

    document_type: Optional[SupportedDocumentType] = Field(
        default=None,
        description="Document type to be used for extraction override workflow parameter",
        alias="document-type",
    )


class WorkflowExecuteRequest(BaseModel):
    """Schema for workflow execution request metadata."""

    metadata: Dict[str, Any] = Field(
        description="Metadata object containing workflow execution parameters",
        json_schema_extra={
            "example": {
                "$metadata": {
                    "source": "email",
                    "priority": "high",
                    "tags": ["invoice", "urgent"],
                    "user_id": "user123",
                    "process_type": "document_analysis",
                }
            }
        },
    )

    @classmethod
    def validate_metadata(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate metadata structure."""

        # Ensure metadata is not empty
        if not v:
            raise ValueError("Metadata cannot be empty")

        return v


class WorkflowExecuteResponse(BaseModel):
    """Schema for workflow execution response."""

    status: str = Field(description="Response status")
    data: WorkflowExecutionData = Field(description="Response data")
    message: str = Field(description="Response message")
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Response timestamp",
    )
