from pydantic import Field

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class AppSettings(BaseDocumentIaSettings):
    # API configuration
    APP_VERSION: str = "1.0.0"

    # Server configuration (let Pydantic parse env and cast types)
    SERVER_HOST: str = Field(default="0.0.0.0", validation_alias="HOST")
    SERVER_PORT: int = Field(default=8000, validation_alias="PORT")
    BASE_URL: str = Field(default="", validation_alias="BASE_URL")


class Settings(AppSettings):
    pass


# Global settings instance
settings = Settings()
