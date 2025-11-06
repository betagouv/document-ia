from pydantic import BaseModel, Field

from document_ia_api.api.contracts.api_key.api_key import APIKeyResult
from document_ia_infra.data.organization.enum.platform_role import PlatformRole


class CreateOrganizationRequest(BaseModel):
    name: str = Field(description="Organization Name", examples=["Acme Corp"])
    contact_email: str = Field(
        description="Organization Contact Email", examples=["ops@acme.io"]
    )
    platform_role: PlatformRole = Field(
        default=PlatformRole.STANDARD, description="Organization Platform Role"
    )


class OrganizationResult(BaseModel):
    id: str = Field(description="Organization ID")
    name: str = Field(description="Organization Name")
    contact_email: str = Field(description="Organization Contact Email")
    platform_role: PlatformRole = Field(description="Organization Platform Role")
    created_at: str = Field(description="Organization Creation Timestamp")
    updated_at: str = Field(description="Organization Update Timestamp")


class OrganizationDetailsResult(OrganizationResult):
    api_keys: list[APIKeyResult] = Field(
        default=[], description="API keys attached to this organization"
    )
