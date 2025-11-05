import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.application.services.api_key.api_key_helper import ApiKeyHelper
from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO
from document_ia_infra.data.api_key.repository.api_key import ApiKeyRepository

logger = logging.getLogger(__name__)


class ApiKeyService:
    def __init__(self, db_session: AsyncSession):
        self.api_key_repository = ApiKeyRepository(db_session)
        self.api_key_helper = ApiKeyHelper()

    async def get_api_key_from_presented_key(
        self, presented_key: str
    ) -> Optional[ApiKeyDTO]:
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
