from typing import Dict, Any, List
from pydantic import BaseModel, Field


class WorkflowExecutionData(BaseModel):
    """Schema for workflow execution data."""

    execution_id: str = Field(description="Unique execution identifier")
    workflow_id: str = Field(description="Workflow identifier")
    status: str = Field(description="Execution status")
    created_at: str = Field(description="Creation timestamp")
    file_info: Dict[str, Any] = Field(description="Uploaded file information")
    metadata: Dict[str, Any] = Field(description="Execution metadata")


class WorkflowDefinition(BaseModel):
    """Schema for workflow definition from JSON file."""

    id: str = Field(description="Unique workflow identifier")
    name: str = Field(description="Workflow name")
    description: str = Field(description="Workflow description")
    version: str = Field(description="Workflow version")
    enabled: bool = Field(description="Whether workflow is enabled")
    supported_file_types: List[str] = Field(description="Supported file MIME types")
    max_file_size_mb: int = Field(description="Maximum file size in MB")
    processing_timeout_minutes: int = Field(description="Processing timeout in minutes")
    created_at: str = Field(description="Creation timestamp")
    updated_at: str = Field(description="Last update timestamp")
