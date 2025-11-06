import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.api.contracts.api_key.api_key import (
    APIKeyResult,
    APIKeyCreatedResult,
)
from document_ia_api.api.exceptions.entity_not_found_exception import (
    HttpEntityNotFoundException,
)
from document_ia_api.application.services.api_key.api_key_helper import ApiKeyHelper
from document_ia_api.application.services.api_key.mapper import (
    map_api_key_dto_to_api_result,
)
from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus
from document_ia_infra.data.api_key.repository.api_key import ApiKeyRepository

logger = logging.getLogger(__name__)


class ApiKeyService:
    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.api_key_repository = ApiKeyRepository(db_session)
        self.api_key_helper = ApiKeyHelper()

    async def update_status(
        self, organization_id: UUID, api_key_id: UUID, api_key_status: ApiKeyStatus
    ) -> APIKeyResult:
        try:
            result = await self.api_key_repository.update_status_by_id(
                organization_id=organization_id,
                status=api_key_status,
                api_key_id=api_key_id,
            )
            if result is None:
                logger.warning(
                    "API key with ID %s not found for organization %s",
                    api_key_id,
                    organization_id,
                )
                raise HttpEntityNotFoundException(
                    entity_name="ApiKey", entity_id=str(api_key_id)
                )
            await self.db_session.commit()
            return map_api_key_dto_to_api_result(result)
        except Exception:
            await self.db_session.rollback()
            raise

    async def delete(self, organization_id: UUID, api_key_id: UUID) -> None:
        try:
            deleted = await self.api_key_repository.delete(organization_id, api_key_id)
            if not deleted:
                logger.warning(
                    "API key with ID %s not found for organization %s",
                    api_key_id,
                    organization_id,
                )
                raise HttpEntityNotFoundException(
                    entity_name="ApiKey", entity_id=str(api_key_id)
                )
            logger.info(
                "Deleted API key with ID %s for organization %s",
                api_key_id,
                organization_id,
            )
            await self.db_session.commit()
        except Exception:
            await self.db_session.rollback()
            raise

    async def create(self, organization_id: UUID) -> APIKeyCreatedResult:
        presented, prefix, _, key_hash = self.api_key_helper.generate_new_api_key()
        try:
            api_key_dto = await self.api_key_repository.create(
                organization_id=organization_id, key_hash=key_hash, prefix=prefix
            )
            logger.info(
                "Created new API key with ID %s for organization %s",
                api_key_dto.id,
                organization_id,
            )
            await self.db_session.commit()
            return APIKeyCreatedResult(
                **map_api_key_dto_to_api_result(api_key_dto).__dict__, key=presented
            )
        except IntegrityError:
            await self.db_session.rollback()
            raise HttpEntityNotFoundException(
                entity_name="Organization", entity_id=str(organization_id)
            )
        except Exception as e:
            await self.db_session.rollback()
            raise e

    async def get_from_presented_key(self, presented_key: str) -> Optional[ApiKeyDTO]:
        try:
            prefix = self.api_key_helper.get_key_prefix(presented_key)
            api_key_dto = await self.api_key_repository.get_by_prefix_with_relation(
                prefix
            )

            if not api_key_dto:
                return None

            if self.api_key_helper.verify_api_key(presented_key, api_key_dto):
                return api_key_dto
            else:
                return None
        except Exception as e:
            logger.error("Error verifying API key: %s", e)
            return None
