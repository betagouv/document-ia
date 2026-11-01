from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from document_ia_infra.data.event.dto.anonymization_enum import AnonymizationStatus
from document_ia_infra.data.event.dto.event_type_enum import EventType


@dataclass
class EventDTO:
    """Transport envelope between the repository and domain-event decoders.

    ``id`` and ``created_at`` belong to the database row. They are deliberately
    independent of the payload's ``event_id`` and ``created_at`` fields.
    """

    id: UUID
    workflow_id: str
    organization_id: UUID
    execution_id: str
    created_at: datetime
    event_type: EventType
    event: dict[str, Any]
    anonymization_status: AnonymizationStatus = AnonymizationStatus.PENDING
