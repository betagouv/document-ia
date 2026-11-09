"""Unit tests for the consumer's terminal-failure callback wiring."""

import json
from uuid import uuid4

import pytest

from document_ia_worker.workflow import terminal_failure


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
