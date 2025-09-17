from typing import Dict, Any
from pydantic import BaseModel, Field

from document_ia_infra.core.model.file_info import FileInfo


class WorkflowExecutionData(BaseModel):
    """Schema for workflow execution data."""

    execution_id: str = Field(description="Unique execution identifier")
    workflow_id: str = Field(description="Workflow identifier")
    status: str = Field(description="Execution status")
    created_at: str = Field(description="Creation timestamp")
    file_info: FileInfo = Field(description="Uploaded file information")
    metadata: Dict[str, Any] = Field(description="Execution metadata")
