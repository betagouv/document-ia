from pydantic import Field, SecretStr, model_validator
from urllib.parse import quote

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class RedisSettings(BaseDocumentIaSettings):
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    REDIS_DB: int = Field(default=0)
    REDIS_PASSWORD: SecretStr = Field(default_factory=lambda: SecretStr("password"))

    REDIS_WORKER_NUMBER: int = Field(default=1)

    REDIS_URL: str | None = Field(default=None)

    EVENT_STREAM_NAME: str = Field(default="event_stream")
    WEBHOOK_STREAM_NAME: str = Field(default="webhook_stream")
    WEBHOOK_CONSUMER_GROUP: str = Field(default="webhook_consumer")
    EVENT_STREAM_EXPIRATION: int = Field(default=300)
    # Kept for configuration compatibility; publishers no longer trim streams.
    EVENT_STREAM_MAXLEN: int = Field(default=100000)
    EVENT_CONSUMER_GROUP: str = Field(default="workflow_execution_consumer")

    ADMISSION_MAX_OUTSTANDING: int = Field(default=1000, ge=2)
    ADMISSION_RESUME_OUTSTANDING: int = Field(default=800, ge=0)
    ADMISSION_MAX_AGE_SECONDS: int = Field(default=300, ge=2)
    ADMISSION_RESUME_AGE_SECONDS: int = Field(default=120, ge=0)
    # Includes completed history and DLQ; retries of accepted work may exceed it.
    ADMISSION_MAX_RETAINED: int = Field(default=10000, ge=2)
    ADMISSION_RESUME_RETAINED: int = Field(default=8000, ge=0)
    STREAM_COMPLETED_RETENTION_SECONDS: int = Field(default=86400, ge=1)
    STREAM_DLQ_RETENTION_SECONDS: int = Field(default=604800, ge=1)
    STREAM_CLEANUP_BATCH_SIZE: int = Field(default=100, ge=1, le=1000)
    # Operator-enabled, shared across instances; 0 keeps normal throughput.
    STREAM_RECOVERY_INTERVAL_MS: int = Field(default=0, ge=0, le=60000)

    @model_validator(mode="after")
    def validate_admission_thresholds(self):
        if self.ADMISSION_RESUME_OUTSTANDING >= self.ADMISSION_MAX_OUTSTANDING:
            raise ValueError("Admission resume count must be below the stop count")
        if self.ADMISSION_RESUME_AGE_SECONDS >= self.ADMISSION_MAX_AGE_SECONDS:
            raise ValueError("Admission resume age must be below the stop age")
        if self.ADMISSION_RESUME_RETAINED >= self.ADMISSION_MAX_RETAINED:
            raise ValueError("Admission resume history must be below the stop count")
        if self.EVENT_STREAM_NAME == self.WEBHOOK_STREAM_NAME:
            raise ValueError("Workflow and webhook streams must be distinct")
        return self

    # Valeur du header `Retry-After` (en secondes) renvoyé quand une exécution ne
    # peut pas être programmée. Bornée pour ne pas inviter le client à attendre
    # indéfiniment une indisponibilité prolongée.
    PUBLISH_RETRY_AFTER_SECONDS: int = Field(default=5, ge=1, le=120)

    def get_redis_url(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        password = quote(self.REDIS_PASSWORD.get_secret_value(), safe="")
        return (
            f"redis://:{password}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        )


redis_settings = RedisSettings()
