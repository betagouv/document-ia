from logging import Filter, LogRecord
from queue import Queue

from logging_loki import LokiQueueHandler
from pydantic import Field

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class LoggingSettings(BaseDocumentIaSettings):
    LOKI_URL: str = Field(default="", validation_alias="LOKI_URL")
    APP_ENV: str = Field(default="prod", validation_alias="APP_ENV")


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


def build_loki_handler(app_name: str) -> LokiQueueHandler:
    """
    Asynchronous Loki handler (queue) for Scalingo.
    Configured via environment variables:
      LOKI_PUSH=https://<domain>/loki/api/v1/push
      LOKI_USER=lokiwriter (if BasicAuth)
      LOKI_PASS=*********
      APP_NAME=document-ia
      APP_ENV=prod|staging|dev
    """
    url = logging_settings.LOKI_URL
    base_tags = {"app": app_name, "env": logging_settings.APP_ENV}
    return LokiQueueHandler(
        Queue(-1),
        url=url,
        auth=None,
        tags=base_tags,
        version="1",
    )
