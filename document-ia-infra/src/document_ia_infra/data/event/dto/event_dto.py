from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass
class EventDTO:
    id: UUID
    workflow_id: str
    execution_id: str
    created_at: datetime
    event_type: str
    event: dict[str, Any]
    version: int
