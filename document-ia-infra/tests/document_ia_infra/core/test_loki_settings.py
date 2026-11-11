import logging
from queue import Queue
from pydantic import SecretStr
from requests import PreparedRequest

from document_ia_infra.core.loki_settings import (
    BoundedLokiQueueHandler,
    LokiBearerAuth,
    LoggingSettings,
    build_loki_auth,
    build_loki_handler,
)


def test_build_loki_auth_returns_none_without_token() -> None:
    assert build_loki_auth(None) is None
    assert build_loki_auth(SecretStr("")) is None
    assert build_loki_auth(SecretStr("   ")) is None


def test_build_loki_auth_returns_bearer_auth() -> None:
    auth = build_loki_auth(SecretStr("my-token"))
    assert isinstance(auth, LokiBearerAuth)
    assert auth.token == "my-token"


def test_loki_bearer_auth_sets_authorization_header() -> None:
    request = PreparedRequest()
    request.prepare(method="POST", url="https://loki.example/loki/api/v1/push")

    result = LokiBearerAuth("my-token")(request)

    assert result.headers["Authorization"] == "Bearer my-token"


def test_logging_settings_reads_bearer_token(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LOKI_BEARER_TOKEN", "env-token")

    settings = LoggingSettings(_env_file=None)

    assert settings.LOKI_BEARER_TOKEN is not None
    assert settings.LOKI_BEARER_TOKEN.get_secret_value() == "env-token"


def test_build_loki_handler_bounded_queue(monkeypatch) -> None:
    monkeypatch.setattr(
        "document_ia_infra.core.loki_settings.LokiQueueHandler.__init__",
        lambda self, q, **kwargs: None,
    )
    handler = build_loki_handler("test-app")
    assert isinstance(handler, BoundedLokiQueueHandler)


def test_bounded_loki_queue_handler_drops_overflow_records() -> None:
    bounded_queue: Queue[logging.LogRecord] = Queue(maxsize=2)
    handler = BoundedLokiQueueHandler.__new__(BoundedLokiQueueHandler)
    handler.queue = bounded_queue

    record1 = logging.LogRecord("test", logging.INFO, "path", 1, "msg1", (), None)
    record2 = logging.LogRecord("test", logging.INFO, "path", 2, "msg2", (), None)
    record3 = logging.LogRecord("test", logging.INFO, "path", 3, "msg3", (), None)

    handler.enqueue(record1)
    handler.enqueue(record2)
    assert bounded_queue.full()

    # The 3rd record should be dropped silently without raising Full
    handler.enqueue(record3)
    assert bounded_queue.qsize() == 2
