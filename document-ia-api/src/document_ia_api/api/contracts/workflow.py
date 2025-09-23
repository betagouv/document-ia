from datetime import datetime
from typing import Dict, Any

from pydantic import BaseModel, Field

from document_ia_api.schemas.workflow import WorkflowExecutionData


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
