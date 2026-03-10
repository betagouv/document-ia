from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.webhook.dto.webhook_dto import WebHookDTO
from document_ia_infra.data.webhook.entity.webhook import WebHookEntity
from document_ia_infra.data.webhook.mapper.webhook_mapper import entity_to_dto
from document_ia_infra.service.webhook_encryption_service import (
    webhook_encryption_service,
)


class WebHookRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, webhook_id: UUID) -> WebHookDTO | None:
        result = await self.session.execute(
            select(WebHookEntity).where(WebHookEntity.id == webhook_id)
        )
        entity = result.scalars().first()
        if entity is None:
            return None
        return entity_to_dto(entity)

    async def create(
        self,
        *,
        organization_id: UUID,
        url: str,
        headers: dict[str, str],
    ) -> WebHookDTO:
        entity = WebHookEntity(
            organization_id=organization_id,
            url=url,
            encrypted_headers=webhook_encryption_service.encrypt_headers(headers),
        )
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity_to_dto(entity)

    async def list_webhooks_by_organization(
        self,
        organization_id: UUID,
    ) -> list[WebHookDTO]:
        result = await self.session.execute(
            select(WebHookEntity).where(
                WebHookEntity.organization_id == organization_id
            )
        )
        entities = result.scalars().all()
        return [entity_to_dto(entity) for entity in entities]

    async def delete(self, webhook_id: UUID) -> bool:
        result = await self.session.execute(
            delete(WebHookEntity)
            .where(WebHookEntity.id == webhook_id)
            .returning(WebHookEntity.id)
        )
        deleted_ids = result.scalars().all()
        return len(deleted_ids) > 0
