from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.api.contracts.webhook.webhook import WebHookResult
from document_ia_api.api.exceptions.entity_not_found_exception import (
    HttpEntityNotFoundException,
)
from document_ia_api.application.services.webhook.mapper import (
    map_webhook_dto_to_api_result,
)
from document_ia_infra.data.webhook.repository.webhook_repository import (
    WebHookRepository,
)


class WebHookService:
    """Service for handling webhook business logic."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.repository = WebHookRepository(session=db_session)

    async def list_by_organization(self, organization_id: UUID) -> list[WebHookResult]:
        dtos = await self.repository.list_webhooks_by_organization(organization_id)
        return [map_webhook_dto_to_api_result(dto) for dto in dtos]

    async def create(
        self,
        *,
        organization_id: UUID,
        url: str,
        headers: dict[str, str],
    ) -> WebHookResult:
        try:
            dto = await self.repository.create(
                organization_id=organization_id, url=url, headers=headers
            )
            await self.db_session.commit()
            return map_webhook_dto_to_api_result(dto)
        except Exception:
            await self.db_session.rollback()
            raise

    async def delete(self, webhook_id: UUID) -> None:
        try:
            deleted = await self.repository.delete(webhook_id)
            if not deleted:
                await self.db_session.rollback()
                raise HttpEntityNotFoundException(
                    entity_name="webhook", entity_id=str(webhook_id)
                )
            await self.db_session.commit()
            return None
        except Exception:
            await self.db_session.rollback()
            raise

    async def get_by_id(self, webhook_id: UUID) -> WebHookResult:
        dto = await self.repository.get_by_id(webhook_id)
        if dto is None:
            raise HttpEntityNotFoundException(
                entity_name="webhook", entity_id=str(webhook_id)
            )
        return map_webhook_dto_to_api_result(dto)
