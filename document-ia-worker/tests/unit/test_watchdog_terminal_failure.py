"""Unit tests for the consumer's terminal-failure callback wiring."""

import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)
from document_ia_worker.workflow import terminal_failure
from document_ia_worker.workflow import workflow_manager as workflow_manager_module
from document_ia_worker.workflow.workflow_manager import WorkflowManager


class _FakeManager:
    instances: list["_FakeManager"] = []

    def __init__(self, message, retry_count: int, is_last_retry: bool = False):
        self.message = message
        self.retry_count = retry_count
        self.is_last_retry = is_last_retry
        self.reasons: list[str] = []
        _FakeManager.instances.append(self)

    async def record_watchdog_terminal_failure(self, reason: str) -> None:
        self.reasons.append(reason)


@pytest.fixture(autouse=True)
def _patch_manager(monkeypatch):
    _FakeManager.instances = []
    monkeypatch.setattr(terminal_failure, "WorkflowManager", _FakeManager)
    yield


async def test_notify_watchdog_terminal_failure_delegates_message_and_retries():
    exec_id = f"exec-{uuid4()}"
    fields = {"data": json.dumps({"workflow_execution_id": exec_id}), "retries": "2"}

    await terminal_failure.notify_watchdog_terminal_failure(
        "1-0", fields, "workflow_timeout"
    )

    assert len(_FakeManager.instances) == 1
    manager = _FakeManager.instances[0]
    assert manager.message.workflow_execution_id == exec_id
    assert manager.retry_count == 2
    assert manager.is_last_retry is True
    assert manager.reasons == ["workflow_timeout"]


async def test_notify_watchdog_terminal_failure_skips_payload_less_message():
    await terminal_failure.notify_watchdog_terminal_failure(
        "1-0", {}, "workflow_timeout"
    )

    assert _FakeManager.instances == []


def _event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    execution_id: str | None = None,
) -> Any:
    return SimpleNamespace(
        event_type=event_type,
        event={} if payload is None else payload,
        execution_id=execution_id if execution_id is not None else str(uuid4()),
        workflow_id=f"wf-{uuid4()}",
        organization_id=uuid4(),
    )


def test_is_terminal_event_distinguishes_retryable_failure():
    """Un échec retryable est intermédiaire : l'échec terminal doit encore être écrit."""
    assert (
        WorkflowManager._is_terminal_event(_event("WorkflowExecutionCompleted")) is True
    )
    assert (
        WorkflowManager._is_terminal_event(
            _event("WorkflowExecutionFailed", {"error_type": "ValueError"})
        )
        is True
    )
    assert (
        WorkflowManager._is_terminal_event(
            _event("WorkflowExecutionFailed", {"error_type": "RetryableException"})
        )
        is False
    )
    assert (
        WorkflowManager._is_terminal_event(_event("WorkflowExecutionStarted")) is False
    )


class _FakeSessionContext:
    async def __aenter__(self) -> Any:
        return object()

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _FakeDatabaseManager:
    instances: list["_FakeDatabaseManager"] = []

    def __init__(self, **_kwargs: Any) -> None:
        self.disposed = False
        _FakeDatabaseManager.instances.append(self)

    def local_session(self) -> _FakeSessionContext:
        return _FakeSessionContext()

    async def dispose_async(self) -> None:
        self.disposed = True


class _FakeEventStoreService:
    last_event: Any = None
    emitted: list[dict[str, Any]] = []

    def __init__(self, _session: Any) -> None:
        pass

    async def get_last_event_for_execution_id(self, _execution_id: str) -> Any:
        return _FakeEventStoreService.last_event

    async def emit_workflow_failed(self, **kwargs: Any) -> None:
        _FakeEventStoreService.emitted.append(kwargs)


class _FakeRedisManager:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def _patch_workflow_resources(monkeypatch):
    _FakeDatabaseManager.instances = []
    _FakeEventStoreService.emitted = []
    monkeypatch.setattr(
        workflow_manager_module, "DatabaseManager", _FakeDatabaseManager
    )
    monkeypatch.setattr(
        workflow_manager_module, "EventStoreService", _FakeEventStoreService
    )
    monkeypatch.setattr(workflow_manager_module, "RedisManager", _FakeRedisManager)


async def test_terminal_failure_writes_and_releases_resources(
    _patch_workflow_resources,
):
    valid_exec_id = str(uuid4())
    _FakeEventStoreService.last_event = _event(
        "WorkflowExecutionStarted", execution_id=valid_exec_id
    )
    manager = WorkflowManager(
        WorkflowExecutionMessage(workflow_execution_id=valid_exec_id),
        2,
        is_last_retry=True,
    )

    await manager.record_watchdog_terminal_failure("workflow_timeout")

    assert len(_FakeEventStoreService.emitted) == 1
    assert _FakeEventStoreService.emitted[0]["error_type"] == "WatchdogTimeout"
    assert _FakeEventStoreService.emitted[0]["retry_count"] == 2
    assert _FakeDatabaseManager.instances[-1].disposed is True
    assert manager._webhook_redis_manager.closed is True


async def test_terminal_failure_releases_resources_on_terminal_shortcut(
    _patch_workflow_resources,
):
    """Sur une exécution déjà terminée, les ressources sont libérées sans rien écrire."""
    valid_exec_id = str(uuid4())
    _FakeEventStoreService.last_event = _event(
        "WorkflowExecutionCompleted", execution_id=valid_exec_id
    )
    manager = WorkflowManager(
        WorkflowExecutionMessage(workflow_execution_id=valid_exec_id),
        2,
        is_last_retry=True,
    )

    await manager.record_watchdog_terminal_failure("workflow_timeout")

    assert _FakeEventStoreService.emitted == []
    assert _FakeDatabaseManager.instances[-1].disposed is True
    assert manager._webhook_redis_manager.closed is True
