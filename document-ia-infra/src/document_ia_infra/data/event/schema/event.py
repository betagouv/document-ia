from abc import ABC
from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from document_ia_infra.data.event.dto.event_type_enum import EventType


class BaseEvent(BaseModel, ABC):
    """Domain event payload, independent of its storage envelope."""

    event_id: UUID = Field(
        description="Domain event identifier, independent of the store row ID",
        default_factory=uuid4,
    )
    organization_id: UUID = Field(description="Organization identifier")
    workflow_id: str = Field(description="Workflow identifier")
    execution_id: str = Field(description="Execution instance identifier")
    created_at: datetime = Field(
        description="Domain occurrence timestamp, independent of persistence time"
    )
    version: int = Field(
        description="Workflow definition version used to select v1/v2 execution semantics"
    )
    event_type: EventType = Field(description="Event type")

    @property
    def workflow_version(self) -> int:
        """Name the persisted ``version`` field by its actual responsibility."""
        return self.version


class EventStoreRecord(BaseModel):
    """Storage envelope paired with its decoded domain event payload."""

    id: UUID = Field(
        description="Store row identifier, independent of payload event_id"
    )
    workflow_id: str = Field(description="Workflow identifier")
    execution_id: str = Field(description="Execution instance identifier")
    organization_id: UUID = Field(description="Organization identifier")
    created_at: datetime = Field(
        description="Persistence timestamp, independent of payload created_at"
    )
    event_type: EventType = Field(description="Type of event")
    event: BaseEvent = Field(description="Decoded domain event payload")


class EventStream(BaseModel):
    """Schema for event stream response."""

    execution_id: str = Field(description="Execution instance identifier")
    workflow_id: str = Field(description="Workflow identifier")
    organization_id: UUID = Field(description="Organization identifier")
    events: List[EventStoreRecord] = Field(description="List of events in the stream")
    total_events: int = Field(description="Total number of events")
    first_event_at: Optional[datetime] = Field(
        default=None, description="Timestamp of first event"
    )
    last_event_at: Optional[datetime] = Field(
        default=None, description="Timestamp of last event"
    )
