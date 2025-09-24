from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from document_ia_infra.data.event.dto.event_type_enum import EventType


@dataclass
class EventDTO:
    id: UUID
    workflow_id: str
    execution_id: str
    created_at: datetime
    event_type: EventType
    event: dict[str, Any]
