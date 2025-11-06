from document_ia_api.api.contracts.organization.organization import OrganizationResult
from document_ia_infra.data.organization.dto.organization_dto import OrganizationDTO


def map_organization_dto_to_api_result(dto: OrganizationDTO):
    return OrganizationResult(
        id=str(dto.id),
        name=dto.name,
        contact_email=dto.contact_email,
        platform_role=dto.platform_role,
        created_at=dto.created_at.isoformat(),
        updated_at=dto.updated_at.isoformat(),
    )
