"""
Event schemas for event sourcing implementation.

This module defines the event schemas used in the event store system,
following event sourcing principles for workflow execution tracking.
"""

from abc import ABC
from datetime import datetime
from typing import Dict, Any, Optional, List
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class BaseEvent(BaseModel, ABC):
    """Base event class with common fields for all events."""

    event_id: UUID = Field(
        description="Unique identifier for this event", default_factory=uuid4
    )
    workflow_id: str = Field(description="Workflow identifier")
    execution_id: str = Field(description="Execution instance identifier")
    created_at: datetime = Field(description="Event timestamp")
    version: int = Field(description="Event version for optimistic locking")
    event_type: str = Field(description="Event type")


class WorkflowExecutionStartedEvent(BaseEvent):
    """Event triggered when workflow execution begins."""

    event_type: str = Field(
        default="WorkflowExecutionStarted", description="Event type"
    )
    file_info: Dict[str, Any] = Field(description="Uploaded file information")
    metadata: Dict[str, Any] = Field(description="Execution metadata")


class WorkflowExecutionStepCompletedEvent(BaseEvent):
    """Event triggered for each workflow step completion."""

    event_type: str = Field(
        default="WorkflowExecutionStepCompleted", description="Event type"
    )
    step_name: str = Field(description="Name of the completed step")
    step_result: Dict[str, Any] = Field(description="Result data from the step")
    execution_time_ms: int = Field(description="Step execution time in milliseconds")
    output_data: Optional[Dict[str, Any]] = Field(
        default=None, description="Step output data"
    )


class WorkflowExecutionCompletedEvent(BaseEvent):
    """Event triggered when entire workflow completes successfully."""

    event_type: str = Field(
        default="WorkflowExecutionCompleted", description="Event type"
    )
    final_result: Dict[str, Any] = Field(description="Final workflow result")
    total_processing_time_ms: int = Field(
        description="Total processing time in milliseconds"
    )
    output_summary: Dict[str, Any] = Field(description="Summary of all outputs")
    steps_completed: int = Field(description="Number of steps completed")


class WorkflowExecutionFailedEvent(BaseEvent):
    """Event triggered when processing fails."""

    event_type: str = Field(default="WorkflowExecutionFailed", description="Event type")
    error_type: str = Field(description="Type of error that occurred")
    error_message: str = Field(description="Detailed error message")
    failed_step: Optional[str] = Field(
        default=None, description="Step where failure occurred"
    )
    retry_count: int = Field(default=0, description="Number of retry attempts")
    stack_trace: Optional[str] = Field(default=None, description="Error stack trace")


class EventStoreRecord(BaseModel):
    """Schema for event store database record."""

    id: UUID = Field(description="Primary key")
    workflow_id: str = Field(description="Workflow identifier")
    execution_id: str = Field(description="Execution instance identifier")
    created_at: datetime = Field(description="Event timestamp")
    event_type: str = Field(description="Type of event")
    # TODO: change to Event (breaking tests...)
    event: Dict[str, Any] = Field(description="Event payload as JSON")
    version: int = Field(description="Event version for optimistic locking")


class EventStream(BaseModel):
    """Schema for event stream response."""

    execution_id: str = Field(description="Execution instance identifier")
    workflow_id: str = Field(description="Workflow identifier")
    events: List[EventStoreRecord] = Field(description="List of events in the stream")
    total_events: int = Field(description="Total number of events")
    first_event_at: Optional[datetime] = Field(
        default=None, description="Timestamp of first event"
    )
    last_event_at: Optional[datetime] = Field(
        default=None, description="Timestamp of last event"
    )
