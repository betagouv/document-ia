from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from document_ia_infra.data.event.dto.anonymization_enum import AnonymizationStatus
from document_ia_infra.data.event.dto.event_type_enum import EventType


@dataclass
class EventDTO:
    id: UUID
    workflow_id: str
    organization_id: UUID
    execution_id: str
    created_at: datetime
    event_type: EventType
    event: dict[str, Any]
    anonymization_status: AnonymizationStatus = AnonymizationStatus.PENDING
