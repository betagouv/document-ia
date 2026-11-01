from typing import Optional, Literal

from pydantic import Field

from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.event import BaseEvent


class WorkflowExecutionFailedEvent(BaseEvent):
    """Event triggered when processing fails."""

    event_type: Literal[EventType.WORKFLOW_EXECUTION_FAILED] = Field(  # pyright: ignore[reportIncompatibleVariableOverride]
        default=EventType.WORKFLOW_EXECUTION_FAILED, description="Event type"
    )
    error_type: str = Field(description="Type of error that occurred")
    error_message: str = Field(description="Detailed error message")
    failed_step: Optional[str] = Field(
        default=None, description="Step where failure occurred"
    )
    retry_count: int = Field(default=0, description="Number of retry attempts")
