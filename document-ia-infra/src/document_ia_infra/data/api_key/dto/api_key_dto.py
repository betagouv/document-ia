from dataclasses import dataclass
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus

if TYPE_CHECKING:
    from document_ia_infra.data.organization.dto.organization_dto import OrganizationDTO


@dataclass
class ApiKeyDTO:
    id: UUID
    organization_id: UUID
    organization: Optional["OrganizationDTO"]
    key_hash: str
    prefix: str
    status: ApiKeyStatus
    created_at: datetime
    updated_at: datetime
