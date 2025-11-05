from typing import Optional, List
from uuid import UUID

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO
from document_ia_infra.data.api_key.entity.api_key import ApiKeyEntity
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus
from document_ia_infra.data.api_key.mapper.api_key_mapper import entity_to_dto

## Need to import this to avoid joinLoad issues when organizationEntity is not in context
from document_ia_infra.data.organization.entity.organization import OrganizationEntity


class ApiKeyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        organization_id: UUID,
        key_hash: str,
        prefix: str,
        status: ApiKeyStatus = ApiKeyStatus.ACTIVE,
    ) -> ApiKeyDTO:
        entity = ApiKeyEntity(
            organization_id=organization_id,
            key_hash=key_hash,
            prefix=prefix,
            status=status.value,
        )
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity_to_dto(entity)

    async def get_by_id(self, api_key_id: UUID) -> Optional[ApiKeyDTO]:
        result = await self.session.execute(
            select(ApiKeyEntity).where(ApiKeyEntity.id == api_key_id)
        )
        entity = result.scalars().first()
        return entity_to_dto(entity) if entity else None

    async def get_by_id_with_relation(self, api_key_id: UUID) -> Optional[ApiKeyDTO]:
        assert OrganizationEntity
        result = await self.session.execute(
            select(ApiKeyEntity)
            .options(joinedload(ApiKeyEntity.organization))
            .where(ApiKeyEntity.id == api_key_id)
        )
        entity = result.scalars().first()
        return entity_to_dto(entity) if entity else None

    async def get_by_prefix_with_relation(self, prefix: str) -> Optional[ApiKeyDTO]:
        assert OrganizationEntity
        result = await self.session.execute(
            select(ApiKeyEntity)
            .options(joinedload(ApiKeyEntity.organization))
            .where(
                (ApiKeyEntity.prefix == prefix)
                & (ApiKeyEntity.status == ApiKeyStatus.ACTIVE.value)
            )
        )
        entity = result.scalars().first()
        return entity_to_dto(entity) if entity else None

    async def list(
        self,
        *,
        organization_id: Optional[UUID] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[ApiKeyDTO]:
        query = select(ApiKeyEntity)
        if organization_id:
            query = query.where(ApiKeyEntity.organization_id == organization_id)
        query = query.order_by(ApiKeyEntity.created_at.asc())
        if offset:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)
        result = await self.session.execute(query)
        entities = result.scalars().all()
        return [entity_to_dto(e) for e in entities]

    async def update(
        self,
        api_key_id: UUID,
        *,
        status: Optional[ApiKeyStatus] = None,
        key_hash: Optional[str] = None,
    ) -> Optional[ApiKeyDTO]:
        values = {}
        if status is not None:
            values["status"] = status.value
        if key_hash is not None:
            values["key_hash"] = key_hash
        if not values:
            return await self.get_by_id(api_key_id)

        await self.session.execute(
            update(ApiKeyEntity).where(ApiKeyEntity.id == api_key_id).values(**values)
        )
        await self.session.flush()
        return await self.get_by_id(api_key_id)

    async def delete(self, api_key_id: UUID) -> bool:
        result = await self.session.execute(
            delete(ApiKeyEntity)
            .where(ApiKeyEntity.id == api_key_id)
            .returning(ApiKeyEntity.id)
        )
        return len(result.scalars().all()) > 0
