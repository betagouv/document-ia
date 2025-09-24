from abc import ABC
from datetime import datetime
from typing import Dict, Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.data.event.dto.event_type_enum import EventType


class BaseEvent(BaseModel, ABC):
    """Base event class with common fields for all events."""

    event_id: UUID = Field(
        description="Unique identifier for this event", default_factory=uuid4
    )
    workflow_id: str = Field(description="Workflow identifier")
    execution_id: str = Field(description="Execution instance identifier")
    created_at: datetime = Field(description="Event timestamp")
    version: int = Field(description="Event version for optimistic locking")
    event_type: EventType = Field(description="Event type")


class WorkflowExecutionStartedEvent(BaseEvent):
    """Event triggered when workflow execution begins."""

    event_type: EventType = Field(
        default=EventType.WORKFLOW_EXECUTION_STARTED, description="Event type"
    )
    file_info: FileInfo = Field(description="Uploaded file information")
    metadata: Dict[str, Any] = Field(description="Execution metadata")


class WorkflowExecutionStepCompletedEvent(BaseEvent):
    """Event triggered for each workflow step completion."""

    event_type: EventType = Field(
        default=EventType.WORKFLOW_EXECUTION_STEP_COMPLETED, description="Event type"
    )
    step_name: str = Field(description="Name of the completed step")
    step_result: Dict[str, Any] = Field(description="Result data from the step")
    execution_time_ms: int = Field(description="Step execution time in milliseconds")
    output_data: Optional[Dict[str, Any]] = Field(
        default=None, description="Step output data"
    )


class WorkflowExecutionCompletedEvent(BaseEvent):
    """Event triggered when entire workflow completes successfully."""

    event_type: EventType = Field(
        default=EventType.WORKFLOW_EXECUTION_COMPLETED, description="Event type"
    )
    final_result: Dict[str, Any] = Field(description="Final workflow result")
    total_processing_time_ms: int = Field(
        description="Total processing time in milliseconds"
    )
    output_summary: Dict[str, Any] = Field(description="Summary of all outputs")
    steps_completed: int = Field(description="Number of steps completed")


class WorkflowExecutionFailedEvent(BaseEvent):
    """Event triggered when processing fails."""

    event_type: EventType = Field(
        default=EventType.WORKFLOW_EXECUTION_FAILED, description="Event type"
    )
    error_type: str = Field(description="Type of error that occurred")
    error_message: str = Field(description="Detailed error message")
    failed_step: Optional[str] = Field(
        default=None, description="Step where failure occurred"
    )
    retry_count: int = Field(default=0, description="Number of retry attempts")
