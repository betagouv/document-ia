from pydantic import SecretStr, Field

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class AlbertEmbeddingSettings(BaseDocumentIaSettings):
    ALBERT_EMBEDDING_API_KEY: SecretStr | None = Field(default=None)
    ALBERT_EMBEDDING_BASE_URL: str | None = Field(default=None)


albert_embedding_settings = AlbertEmbeddingSettings()
