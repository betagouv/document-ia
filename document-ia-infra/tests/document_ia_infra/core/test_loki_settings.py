from typing import Any
import logging
from queue import Queue
from unittest.mock import MagicMock

from pydantic import SecretStr
import requests
from requests import PreparedRequest

from document_ia_infra.core.loki_settings import (
    DEFAULT_LOKI_TIMEOUT_S,
    BoundedLokiQueueHandler,
    LokiBearerAuth,
    LoggingSettings,
    _TimeoutSession,
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
    captured_queues: list[Queue[Any]] = []

    def mock_init(self, q: Queue[Any], **kwargs: Any) -> None:
        captured_queues.append(q)

    monkeypatch.setattr(
        "document_ia_infra.core.loki_settings.LokiQueueHandler.__init__",
        mock_init,
    )
    handler = build_loki_handler("test-app")
    assert isinstance(handler, BoundedLokiQueueHandler)
    assert len(captured_queues) == 1
    assert captured_queues[0].maxsize == 1000


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


def test_timeout_session_sets_default_timeout(monkeypatch) -> None:
    session = _TimeoutSession()
    mock_request = MagicMock()
    monkeypatch.setattr(requests.Session, "request", mock_request)

    session.request("POST", "https://loki.example/loki/api/v1/push", json={})
    mock_request.assert_called_once_with(
        "POST",
        "https://loki.example/loki/api/v1/push",
        json={},
        timeout=DEFAULT_LOKI_TIMEOUT_S,
    )

    # Explicit timeout should be preserved
    mock_request.reset_mock()
    session.request(
        "POST", "https://loki.example/loki/api/v1/push", json={}, timeout=10.0
    )
    mock_request.assert_called_once_with(
        "POST", "https://loki.example/loki/api/v1/push", json={}, timeout=10.0
    )


def test_bounded_loki_queue_handler_configures_timeout_session() -> None:
    queue: Queue[logging.LogRecord] = Queue(maxsize=10)
    handler = BoundedLokiQueueHandler(
        queue, url="https://loki.example/push", version="1"
    )
    try:
        assert handler.handler.emitter.session_class is _TimeoutSession
    finally:
        handler.listener.stop()


def test_bounded_loki_queue_handler_skips_prepare_when_full(monkeypatch) -> None:
    queue: Queue[logging.LogRecord] = Queue(maxsize=1)
    handler = BoundedLokiQueueHandler.__new__(BoundedLokiQueueHandler)
    handler.queue = queue

    record1 = logging.LogRecord("test", logging.INFO, "path", 1, "msg1", (), None)
    record2 = logging.LogRecord("test", logging.INFO, "path", 2, "msg2", (), None)

    mock_prepare = MagicMock(return_value=record2)
    monkeypatch.setattr(handler, "prepare", mock_prepare)

    # First record fits in queue
    handler.emit(record1)
    assert queue.qsize() == 1
    assert queue.full()
    assert mock_prepare.call_count == 1

    # Second record when queue is full: prepare must NOT be called
    mock_prepare.reset_mock()
    handler.emit(record2)
    mock_prepare.assert_not_called()
    assert queue.qsize() == 1
