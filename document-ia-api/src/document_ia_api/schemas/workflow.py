from typing import Dict, Any
from pydantic import BaseModel, Field


class WorkflowExecutionData(BaseModel):
    """Schema for workflow execution data."""

    execution_id: str = Field(description="Unique execution identifier")
    workflow_id: str = Field(description="Workflow identifier")
    status: str = Field(description="Execution status")
    created_at: str = Field(description="Creation timestamp")
    file_info: Dict[str, Any] = Field(description="Uploaded file information")
    metadata: Dict[str, Any] = Field(description="Execution metadata")
