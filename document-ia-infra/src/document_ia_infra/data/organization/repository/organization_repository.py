import logging
from typing import Optional, List
from uuid import UUID

from sqlalchemy import select, update, delete
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.organization.dto.organization_dto import OrganizationDTO
from document_ia_infra.data.organization.entity.organization import OrganizationEntity
from document_ia_infra.data.organization.enum.platform_role import PlatformRole
from document_ia_infra.data.organization.mapper.organization_mapper import (
    entity_to_dto,
    entities_to_dtos,
)

logger = logging.getLogger(__name__)


class OrganizationRepository:
    """Repository for Organization CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        contact_email: str,
        name: str,
        platform_role: PlatformRole = PlatformRole.STANDARD,
    ) -> OrganizationDTO:
        entity = OrganizationEntity(
            contact_email=contact_email,
            name=name,
            platform_role=platform_role.value,
        )
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity_to_dto(entity)

    async def get_by_id(self, org_id: UUID) -> Optional[OrganizationDTO]:
        result = await self.session.execute(
            select(OrganizationEntity).where(OrganizationEntity.id == org_id)
        )
        entity = result.scalars().first()
        return entity_to_dto(entity) if entity else None

    async def get_with_api_keys(self, org_id: str) -> Optional[OrganizationDTO]:
        result = await self.session.execute(
            select(OrganizationEntity)
            .options(joinedload(OrganizationEntity.api_keys))
            .where(OrganizationEntity.id == org_id)
        )
        entity = result.scalars().first()
        return entity_to_dto(entity) if entity else None

    async def list(
        self, limit: Optional[int] = None, offset: int = 0
    ) -> List[OrganizationDTO]:
        query = select(OrganizationEntity).order_by(OrganizationEntity.created_at.asc())
        if offset:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)
        result = await self.session.execute(query)
        entities = result.scalars().all()
        return entities_to_dtos(entities)

    async def update(
        self,
        org_id: UUID,
        *,
        contact_email: Optional[str] = None,
        name: Optional[str] = None,
        platform_role: Optional[PlatformRole] = None,
    ) -> Optional[OrganizationDTO]:
        values = {}
        if contact_email is not None:
            values["contact_email"] = contact_email
        if name is not None:
            values["name"] = name
        if platform_role is not None:
            values["platform_role"] = platform_role.value
        if not values:
            return await self.get_by_id(org_id)

        await self.session.execute(
            update(OrganizationEntity)
            .where(OrganizationEntity.id == org_id)
            .values(**values)
        )
        await self.session.flush()
        # Re-fetch updated entity
        return await self.get_by_id(org_id)

    async def delete(self, org_id: UUID) -> bool:
        result = await self.session.execute(
            delete(OrganizationEntity)
            .where(OrganizationEntity.id == org_id)
            .returning(OrganizationEntity.id)
        )
        deleted_ids = result.scalars().all()
        return len(deleted_ids) > 0
