from typing import Dict, Any

from pydantic import Field

from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.event import BaseEvent


class WorkflowExecutionStartedEvent(BaseEvent):
    """Event triggered when workflow execution begins."""

    event_type: EventType = Field(
        default=EventType.WORKFLOW_EXECUTION_STARTED, description="Event type"
    )
    file_info: FileInfo = Field(description="Uploaded file information")
    metadata: Dict[str, Any] = Field(description="Execution metadata")
