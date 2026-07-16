from typing import Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.data.workflow.dto.workflow_v2_dto import WorkflowV2Dto


class WorkflowExecutionData(BaseModel):
    """Schema for workflow execution data."""

    execution_id: str = Field(description="Unique execution identifier")
    workflow_id: str = Field(description="Workflow identifier")
    status: str = Field(description="Execution status")
    created_at: str = Field(description="Creation timestamp")
    file_info: Optional[FileInfo] = Field(description="Uploaded file information")
    file_url: Optional[str] = Field(
        default=None, description="URL of the file to be processed"
    )
    metadata: Dict[str, Any] = Field(description="Execution metadata")


class WorkflowExecutionDataV2(BaseModel):
    """Schema for workflow v2 execution data."""

    execution_id: str = Field(description="Unique execution identifier")
    workflow_id: str = Field(description="Workflow identifier")
    organization_id: UUID = Field(description="Organization identifier")
    status: str = Field(description="Execution status")
    created_at: str = Field(description="Creation timestamp")
    file_info: Optional[FileInfo] = Field(description="Uploaded file information")
    file_url: Optional[str] = Field(
        default=None, description="URL of the file to be processed"
    )
    metadata: Dict[str, Any] = Field(description="Execution metadata")
    workflow_configuration: WorkflowV2Dto = Field(
        description="Resolved workflow configuration (YAML + overrides) sent for execution"
    )
