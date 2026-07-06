from pydantic import Field, SecretStr, HttpUrl
from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class AutoScalerSettings(BaseDocumentIaSettings):
    SCALINGO_API_TOKEN: SecretStr | None = Field(
        default=None, validation_alias="SCALINGO_API_TOKEN"
    )
    SCALINGO_APP_NAME: str | None = Field(
        default=None, validation_alias="SCALINGO_APP_NAME"
    )
    API_HEALTH_URL: HttpUrl | None = Field(
        default=None, validation_alias="API_HEALTH_URL"
    )

    SCALINGO_API_URL: HttpUrl = Field(
        default=HttpUrl("https://api.osc-secnum-fr1.scalingo.com"),
        validation_alias="SCALINGO_API_URL",
    )
    SCALINGO_AUTH_URL: HttpUrl = Field(
        default=HttpUrl("https://auth.scalingo.com"),
        validation_alias="SCALINGO_AUTH_URL",
    )

    CHECK_INTERVAL: int = Field(default=30, validation_alias="CHECK_INTERVAL")
    THREAD_PER_WORKER: int = Field(default=10, validation_alias="THREAD_PER_WORKER")
    MIN_WORKERS: int = Field(default=1, validation_alias="MIN_WORKERS")
    MAX_WORKERS: int = Field(default=5, validation_alias="MAX_WORKERS")

    SCALE_UP_COOLDOWN: int = Field(default=120, validation_alias="SCALE_UP_COOLDOWN")
    SCALE_DOWN_COOLDOWN: int = Field(
        default=120, validation_alias="SCALE_DOWN_COOLDOWN"
    )


settings = AutoScalerSettings()
