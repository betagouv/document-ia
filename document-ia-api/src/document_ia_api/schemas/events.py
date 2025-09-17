"""
Event schemas for event sourcing implementation.

This module defines the event schemas used in the event store system,
following event sourcing principles for workflow execution tracking.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from uuid import UUID

from pydantic import BaseModel, Field

from document_ia_infra.data.event.dto.event_type_enum import EventType


class EventStoreRecord(BaseModel):
    """Schema for event store database record."""

    id: UUID = Field(description="Primary key")
    workflow_id: str = Field(description="Workflow identifier")
    execution_id: str = Field(description="Execution instance identifier")
    created_at: datetime = Field(description="Event timestamp")
    event_type: EventType = Field(description="Type of event")
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
