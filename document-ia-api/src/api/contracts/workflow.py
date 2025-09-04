from pydantic import BaseModel, Field, field_validator
from typing import Dict, Any, Optional
from datetime import datetime

from schemas.workflow import WorkflowExecutionData


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

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v):
        """Validate metadata structure."""
        if not isinstance(v, dict):
            raise ValueError("Metadata must be a JSON object")

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


class WorkflowErrorResponse(BaseModel):
    """Schema for workflow error responses."""

    status: str = Field(default="error", description="Response status")
    error: str = Field(description="Error type")
    message: str = Field(description="Error message")
    details: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional error details"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Error timestamp",
    )
