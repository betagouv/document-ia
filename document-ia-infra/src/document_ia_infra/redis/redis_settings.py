from pydantic import Field, SecretStr

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
    EVENT_STREAM_MAXLEN: int = Field(default=1000)
    EVENT_CONSUMER_GROUP: str = Field(default="workflow_execution_consumer")

    def get_redis_url(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


redis_settings = RedisSettings()
