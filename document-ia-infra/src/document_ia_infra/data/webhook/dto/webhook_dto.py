from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class WebHookDTO:
    id: UUID
    organization_id: UUID
    url: str
    headers: dict[str, str]
    created_at: datetime
    updated_at: datetime
