import logging

import httpx

from document_ia_worker.core.embedding.albert.albert_embedding_models import (
    AlbertEmbeddingRequest,
    AlbertEmbeddingResponse,
)
from document_ia_worker.core.embedding.albert.albert_embedding_settings import (
    AlbertEmbeddingSettings,
    albert_embedding_settings,
)
from document_ia_worker.exception.http_embedding_miss_configuration_exception import (
    HTTPEmbeddingMissConfigurationException,
)

logger = logging.getLogger(__name__)


class AlbertHttpEmbeddingService:
    def __init__(
        self,
        config: AlbertEmbeddingSettings = albert_embedding_settings,
        timeout: int = 60,
        connection_timeout: int = 60,
    ):
        self.config = config
        self.timeout = timeout
        self.connection_timeout = connection_timeout

    async def create_embeddings(
        self,
        *,
        input_data: list[int] | list[list[int]] | str | list[str],
        model: str = "openweight-embeddings",
        dimensions: int | None = None,
        encoding_format: str | None = None,
    ) -> AlbertEmbeddingResponse:
        request_payload = AlbertEmbeddingRequest(
            input=input_data,
            model=model,
            dimensions=dimensions,
            encoding_format=encoding_format,
        )

        timeout = httpx.Timeout(self.timeout, connect=self.connection_timeout)
        headers = {
            "Authorization": f"Bearer {self.get_api_key()}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.get_base_url()}/embeddings",
                headers=headers,
                json=request_payload.model_dump(mode="json", exclude_none=True),
            )

        response.raise_for_status()
        return AlbertEmbeddingResponse.model_validate_json(response.text)

    def get_api_key(self) -> str:
        if self.config.ALBERT_EMBEDDING_API_KEY is None:
            raise HTTPEmbeddingMissConfigurationException("Albert")
        return self.config.ALBERT_EMBEDDING_API_KEY.get_secret_value()

    def get_base_url(self) -> str:
        if self.config.ALBERT_EMBEDDING_BASE_URL is None:
            raise HTTPEmbeddingMissConfigurationException("Albert")
        return self.config.ALBERT_EMBEDDING_BASE_URL
