from logging import Filter, LogRecord
from queue import Queue

from logging_loki import LokiQueueHandler
from pydantic import Field, SecretStr
from requests import PreparedRequest
from requests.auth import AuthBase

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class LoggingSettings(BaseDocumentIaSettings):
    LOKI_URL: str = Field(default="", validation_alias="LOKI_URL")
    APP_ENV: str = Field(default="prod", validation_alias="APP_ENV")
    LOKI_LOGGING_ENABLED: bool = Field(
        default=True, validation_alias="LOKI_LOGGING_ENABLED"
    )
    LOKI_BEARER_TOKEN: SecretStr | None = Field(
        default=None, validation_alias="LOKI_BEARER_TOKEN"
    )


logging_settings = LoggingSettings()


class LokiTagsFilter(Filter):
    """
    Adds dynamic 'logger' and 'level' labels to record.tags.
    (python-logging-loki merges handler-provided 'tags' with record.tags)
    """

    def filter(self, record: LogRecord) -> bool:
        tags = getattr(record, "tags", {}) or {}
        tags.setdefault("logger", record.name if record.name else "root")
        tags.setdefault("level", record.levelname)
        record.tags = tags
        return True


class LokiBearerAuth(AuthBase):
    """Adds `Authorization: Bearer <token>` on each Loki push request."""

    def __init__(self, token: str) -> None:
        self.token = token

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request


def build_loki_auth(token: SecretStr | None) -> LokiBearerAuth | None:
    if token is None:
        return None
    value = token.get_secret_value().strip()
    if not value:
        return None
    return LokiBearerAuth(value)


def build_loki_handler(app_name: str) -> LokiQueueHandler:
    """
    Asynchronous Loki handler (queue) for Scalingo.
    Configured via environment variables:
      LOKI_URL=https://<domain>/loki/api/v1/push
      LOKI_BEARER_TOKEN=********* (optional Bearer token)
      APP_ENV=prod|staging|dev
    """
    url = logging_settings.LOKI_URL
    base_tags = {"app": app_name, "env": logging_settings.APP_ENV}
    return LokiQueueHandler(
        Queue(-1),
        url=url,
        auth=build_loki_auth(logging_settings.LOKI_BEARER_TOKEN),
        tags=base_tags,
        version="1",
    )
