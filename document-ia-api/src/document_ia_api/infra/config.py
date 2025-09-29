from pydantic import Field

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class Settings(BaseDocumentIaSettings):
    # Application settings
    AUTO_MIGRATE: bool = Field(default=True)

    # Rate limiting configuration
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(default=300)
    RATE_LIMIT_REQUESTS_PER_DAY: int = Field(default=5000)


# Global settings instance
settings = Settings()
