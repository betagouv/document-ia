from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class WorkflowExecutionData(BaseModel):
    """Schema for workflow execution data."""

    execution_id: str = Field(description="Unique execution identifier")
    workflow_id: str = Field(description="Workflow identifier")
    status: str = Field(description="Execution status")
    created_at: str = Field(description="Creation timestamp")
    estimated_completion: Optional[str] = Field(
        default=None, description="Estimated completion timestamp"
    )
    file_info: Dict[str, Any] = Field(description="Uploaded file information")
    metadata: Dict[str, Any] = Field(description="Execution metadata")
