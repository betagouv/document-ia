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


def _event(event_type: str, payload: dict[str, Any] | None = None) -> Any:
    return SimpleNamespace(
        event_type=event_type,
        event={} if payload is None else payload,
        execution_id=f"exec-{uuid4()}",
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


class _FakeSession:
    async def commit(self) -> None:
        pass


class _FakeSessionContext:
    async def __aenter__(self) -> Any:
        return _FakeSession()

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
    started_event: Any = None
    emitted: list[dict[str, Any]] = []

    def __init__(self, _session: Any) -> None:
        pass

    async def get_last_event_for_execution_id(self, _execution_id: str) -> Any:
        return _FakeEventStoreService.last_event

    async def get_workflow_started_event(self, _execution_id: str) -> Any:
        return _FakeEventStoreService.started_event

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
    _FakeEventStoreService.last_event = None
    _FakeEventStoreService.started_event = None
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
    _FakeEventStoreService.last_event = _event("WorkflowExecutionStarted")
    manager = WorkflowManager(
        WorkflowExecutionMessage(workflow_execution_id="exec-1"),
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
    _FakeEventStoreService.last_event = _event("WorkflowExecutionCompleted")
    manager = WorkflowManager(
        WorkflowExecutionMessage(workflow_execution_id="exec-1"),
        2,
        is_last_retry=True,
    )

    await manager.record_watchdog_terminal_failure("workflow_timeout")

    assert _FakeEventStoreService.emitted == []
    assert _FakeDatabaseManager.instances[-1].disposed is True
    assert manager._webhook_redis_manager.closed is True


async def test_record_watchdog_terminal_failure_deletes_s3_file(
    _patch_workflow_resources, monkeypatch, caplog
):
    import logging
    from pydantic import SecretStr

    raw_s3_key = "sensitive/customer_uploads/document.pdf"
    fake_s3_file_info = SimpleNamespace(
        s3_key=SecretStr(raw_s3_key),
    )
    started_event_obj = SimpleNamespace(
        s3_file_info=fake_s3_file_info,
    )
    last_event_obj = _event("WorkflowExecutionStarted")

    _FakeEventStoreService.last_event = last_event_obj
    _FakeEventStoreService.started_event = (last_event_obj, started_event_obj)

    deleted_keys: list[str] = []

    class _FakeS3Manager:
        def delete_file(self, s3_key: str) -> bool:
            deleted_keys.append(s3_key)
            return True

    monkeypatch.setattr(workflow_manager_module, "S3Manager", _FakeS3Manager)

    manager = WorkflowManager(
        WorkflowExecutionMessage(workflow_execution_id=last_event_obj.execution_id),
        2,
        is_last_retry=True,
    )

    with caplog.at_level(logging.INFO):
        await manager.record_watchdog_terminal_failure("workflow_timeout")

    assert deleted_keys == [raw_s3_key]
    assert raw_s3_key not in caplog.text
    assert "Watchdog terminal failure: S3 file deleted for execution" in caplog.text


async def test_record_watchdog_terminal_failure_still_purges_s3_when_already_terminal(
    _patch_workflow_resources, monkeypatch
):
    from pydantic import SecretStr

    raw_s3_key = "sensitive/completed_execution/document.pdf"
    fake_s3_file_info = SimpleNamespace(
        s3_key=SecretStr(raw_s3_key),
    )
    started_event_obj = SimpleNamespace(
        s3_file_info=fake_s3_file_info,
    )
    last_event_obj = _event("WorkflowExecutionCompleted")

    _FakeEventStoreService.last_event = last_event_obj
    _FakeEventStoreService.started_event = (last_event_obj, started_event_obj)

    deleted_keys: list[str] = []

    class _FakeS3Manager:
        def delete_file(self, s3_key: str) -> bool:
            deleted_keys.append(s3_key)
            return True

    monkeypatch.setattr(workflow_manager_module, "S3Manager", _FakeS3Manager)

    manager = WorkflowManager(
        WorkflowExecutionMessage(workflow_execution_id=last_event_obj.execution_id),
        2,
        is_last_retry=True,
    )

    await manager.record_watchdog_terminal_failure("workflow_timeout")

    assert _FakeEventStoreService.emitted == []
    assert deleted_keys == [raw_s3_key]


async def test_start_purges_s3_on_terminal_prepare_workflow_failure(
    _patch_workflow_resources, monkeypatch
):
    from pydantic import SecretStr
    from document_ia_worker.exception.workflow_not_found_exception import (
        WorkflowNotFoundException,
    )

    raw_s3_key = "sensitive/prepare_failure/document.pdf"
    fake_s3_file_info = SimpleNamespace(
        s3_key=SecretStr(raw_s3_key),
    )
    started_event_obj = SimpleNamespace(
        s3_file_info=fake_s3_file_info,
    )
    started_event_dto = _event("WorkflowExecutionStarted")

    _FakeEventStoreService.started_event = (started_event_dto, started_event_obj)

    deleted_keys: list[str] = []

    class _FakeS3Manager:
        def delete_file(self, s3_key: str) -> bool:
            deleted_keys.append(s3_key)
            return True

    monkeypatch.setattr(workflow_manager_module, "S3Manager", _FakeS3Manager)

    exec_id = started_event_dto.execution_id
    manager = WorkflowManager(
        WorkflowExecutionMessage(workflow_execution_id=exec_id),
        0,
        is_last_retry=False,
    )

    async def failing_prepare(_session):
        raise WorkflowNotFoundException("Workflow wf-test not found")

    monkeypatch.setattr(manager, "_prepare_workflow", failing_prepare)

    with pytest.raises(WorkflowNotFoundException):
        await manager.start()

    assert deleted_keys == [raw_s3_key]


async def test_execute_workflow_cleanup_continues_if_later_step_cleanup_raises(
    _patch_workflow_resources, monkeypatch
):
    from unittest.mock import AsyncMock

    from document_ia_worker.workflow.main_workflow_context import (
        MainWorkflowContext,
    )
    from datetime import datetime, UTC

    manager = WorkflowManager(
        WorkflowExecutionMessage(workflow_execution_id="exec-cleanup-resilience"),
        0,
        is_last_retry=False,
    )
    manager.main_workflow_context = MainWorkflowContext(
        execution_id="exec-cleanup-resilience",
        organization_id=uuid4(),
        workflow_version=1,
        start_time=datetime.now(UTC),
        steps_metadata=[],
    )

    from unittest.mock import MagicMock
    from document_ia_worker.exception.workflow_step_exception import (
        WorkflowStepException,
    )

    step1 = SimpleNamespace(
        cleanup=AsyncMock(return_value=None),
        execute=AsyncMock(return_value=("res1", None)),
        inject_workflow_context=MagicMock(),
        get_context_result_key=MagicMock(return_value="key1"),
    )
    step2 = SimpleNamespace(
        cleanup=AsyncMock(side_effect=RuntimeError("Step 2 cleanup failed")),
        execute=AsyncMock(side_effect=RuntimeError("Step 2 failed")),
        inject_workflow_context=MagicMock(),
        get_context_result_key=MagicMock(return_value="key2"),
    )

    manager.step_list = [step1, step2]

    with pytest.raises(WorkflowStepException) as exc_info:
        await manager._execute_workflow()

    assert "Step 2 failed" in str(exc_info.value.inner_exception)

    assert step2.cleanup.called is True
    assert step1.cleanup.called is True
