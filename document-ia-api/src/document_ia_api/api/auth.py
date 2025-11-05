from typing import Optional

from fastapi import Depends, Request, Security, HTTPException, Header
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.application.services.api_key.api_key_service import ApiKeyService
from document_ia_infra.data.database import database_manager
from document_ia_infra.data.organization.dto.organization_dto import OrganizationDTO

# Security scheme for API Key authentication
security = APIKeyHeader(name="X-API-KEY")


async def verify_api_key(
    request: Request,
    api_key: str = Security(security),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
):
    apikey_service = ApiKeyService(db_session)

    api_key_dto = await apikey_service.get_api_key_from_presented_key(api_key)

    if not api_key_dto:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not api_key_dto.organization:
        raise HTTPException(
            status_code=401, detail="API key has no associated organization"
        )

    request.state.organization = api_key_dto.organization

    return api_key_dto


def get_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-KEY")):
    """Get API key from header without requiring authentication."""
    return x_api_key


def get_current_organization(request: Request) -> OrganizationDTO:
    organization = getattr(request.state, "organization", None)
    if not organization and not isinstance(organization, OrganizationDTO):
        raise HTTPException(
            status_code=403, detail="Unauthorized access: No organization found"
        )

    return organization
