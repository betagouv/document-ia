from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from document_ia_api.api.contracts.api_key.api_key import APIKeyResult
from document_ia_api.api.contracts.organization.organization import (
    OrganizationResult,
    OrganizationDetailsResult,
)
from document_ia_api.api.exceptions.entity_not_found_exception import (
    HttpEntityNotFoundException,
)
from document_ia_api.application.services.api_key.mapper import (
    map_api_key_dto_to_api_result,
)
from document_ia_api.application.services.organization.mapper import (
    map_organization_dto_to_api_result,
)
from document_ia_infra.data.organization.repository.organization_repository import (
    OrganizationRepository,
)
from document_ia_infra.exception.entity_not_found_exception import (
    EntityNotFoundException,
)
from document_ia_infra.data.organization.enum.platform_role import PlatformRole


class OrganizationService:
    """Service for handling execution business logic."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.organization_repository = OrganizationRepository(session=db_session)

    async def get_all_organizations(self) -> list[OrganizationResult]:
        organizations_dto = await self.organization_repository.list()
        return [
            map_organization_dto_to_api_result(organization_dto)
            for organization_dto in organizations_dto
        ]

    async def get_organization_details_by_id(
        self, organization_id: str
    ) -> OrganizationDetailsResult:
        organization_dto = await self.organization_repository.get_with_api_keys(
            organization_id
        )
        if not organization_dto:
            raise HttpEntityNotFoundException(
                entity_name="organization", entity_id=organization_id
            )

        api_keys: list[APIKeyResult] = []

        if organization_dto.api_keys is not None:
            for dto in organization_dto.api_keys:
                api_keys.append(map_api_key_dto_to_api_result(dto))

        return OrganizationDetailsResult(
            **map_organization_dto_to_api_result(organization_dto).__dict__,
            api_keys=api_keys,
        )

    async def create(
        self, name: str, contact_email: str, platform_role: PlatformRole
    ) -> OrganizationResult:
        try:
            dto = await self.organization_repository.create(
                contact_email=contact_email,
                name=name,
                platform_role=platform_role,
            )
            await self.db_session.commit()
            return map_organization_dto_to_api_result(dto)
        except Exception:
            await self.db_session.rollback()
            raise

    async def delete(self, organization_id: str) -> None:
        try:
            deleted = await self.organization_repository.delete(UUID(organization_id))
            if not deleted:
                await self.db_session.rollback()
                raise EntityNotFoundException(
                    entity_name="organization", entity_id=organization_id
                )
            await self.db_session.commit()
            return None
        except Exception:
            await self.db_session.rollback()
            raise
