from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from typing import Optional, List, TYPE_CHECKING

from document_ia_infra.data.organization.enum.platform_role import PlatformRole

if TYPE_CHECKING:
    from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO


@dataclass
class OrganizationDTO:
    id: UUID
    contact_email: str
    name: str
    platform_role: PlatformRole
    created_at: datetime
    updated_at: datetime
    api_keys: Optional[List["ApiKeyDTO"]] = None
