from logging import Filter, LogRecord
from queue import Full, Queue
from typing import Any, cast

from logging_loki import LokiQueueHandler
from pydantic import Field, SecretStr
import requests
from requests import PreparedRequest, Response
from requests.auth import AuthBase

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings

DEFAULT_LOKI_TIMEOUT_S = 5.0


class _TimeoutSession(requests.Session):
    """Requests session enforcing a default HTTP timeout to prevent QueueListener hangs."""

    def request(self, method: str, url: str, **kwargs: Any) -> Response:  # type: ignore[override]
        kwargs.setdefault("timeout", DEFAULT_LOKI_TIMEOUT_S)
        return super().request(method, url, **kwargs)


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


class BoundedLokiQueueHandler(LokiQueueHandler):
    """
    Asynchronous Loki queue handler with a bounded buffer and HTTP timeout.
    Silently drops excess records when the queue is full (e.g. during Loki downtime)
    to prevent memory exhaustion or application blocking.
    """

    def __init__(self, queue: Queue[Any], **kwargs: Any) -> None:
        super().__init__(queue, **kwargs)  # pyright: ignore [reportUnknownMemberType]
        if hasattr(self, "handler") and hasattr(self.handler, "emitter"):
            self.handler.emitter.session_class = _TimeoutSession
            if hasattr(self.handler.emitter, "close"):
                self.handler.emitter.close()

    def emit(self, record: LogRecord) -> None:
        queue_obj = cast(Queue[Any], self.queue)
        if hasattr(queue_obj, "full") and queue_obj.full():
            return  # Skip expensive self.prepare(record) formatting/copying when full
        super().emit(record)

    def enqueue(self, record: LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except Full:
            pass  # Silently drop log records when queue is saturated


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
    return BoundedLokiQueueHandler(
        Queue(maxsize=1000),
        url=url,
        auth=build_loki_auth(logging_settings.LOKI_BEARER_TOKEN),
        tags=base_tags,
        version="1",
    )
