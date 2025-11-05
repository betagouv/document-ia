from pydantic import Field, SecretStr

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class AppSettings(BaseDocumentIaSettings):
    # API configuration
    APP_VERSION: str = "1.0.0"

    # Server configuration (let Pydantic parse env and cast types)
    SERVER_HOST: str = Field(default="0.0.0.0", validation_alias="HOST")
    SERVER_PORT: int = Field(default=8000, validation_alias="PORT")
    BASE_URL: str = Field(default="", validation_alias="BASE_URL")


class AuthenticationSettings(BaseDocumentIaSettings):
    # API Key for authentication (optional)
    API_KEY: SecretStr | None = Field(default=None, validation_alias="API_KEY")


class Settings(AppSettings, AuthenticationSettings):
    pass


# Global settings instance
settings = Settings()
