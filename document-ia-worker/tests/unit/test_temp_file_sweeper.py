"""Unit tests for TempFileSweeper and ActiveExecutionTracker (Issue #158)."""

import asyncio
import os
import stat
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from document_ia_infra.core.file.safe_path import (
    ensure_directory_permissions,
    ensure_file_permissions,
)
from document_ia_infra.exception.security_exception import PathTraversalException
from document_ia_worker.core.temp_file_sweeper import (
    ActiveExecutionTracker,
    TempFileSweeper,
)


@pytest.fixture(autouse=True)
def clean_tracker():
    """Ensure ActiveExecutionTracker is clean before and after every test."""
    ActiveExecutionTracker.clear()
    yield
    ActiveExecutionTracker.clear()


# ==============================================================================
# 1. Tests for Permissions (0o700 / 0o600)
# ==============================================================================


def test_ensure_directory_permissions(tmp_path: Path):
    target = tmp_path / "sandbox_test"
    result = ensure_directory_permissions(target, 0o700)

    assert result.exists()
    assert result.is_dir()
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o700


def test_ensure_directory_permissions_rejects_symlink(tmp_path: Path):
    target = tmp_path / "real_dir"
    target.mkdir()
    sym = tmp_path / "sym_dir"
    sym.symlink_to(target, target_is_directory=True)

    with pytest.raises(PathTraversalException, match="symlink"):
        ensure_directory_permissions(sym, 0o700)


def test_ensure_file_permissions(tmp_path: Path):
    target_file = tmp_path / "payload.json"
    target_file.write_text("{}", encoding="utf-8")
    result = ensure_file_permissions(target_file, 0o600)

    assert result.exists()
    mode = stat.S_IMODE(target_file.stat().st_mode)
    assert mode == 0o600


def test_ensure_file_permissions_rejects_symlink(tmp_path: Path):
    real_file = tmp_path / "real.txt"
    real_file.write_text("data", encoding="utf-8")
    sym_file = tmp_path / "sym.txt"
    sym_file.symlink_to(real_file)

    with pytest.raises(PathTraversalException, match="symlink"):
        ensure_file_permissions(sym_file, 0o600)


# ==============================================================================
# 2. Tests for ActiveExecutionTracker (Thread Safety & Operations)
# ==============================================================================


def test_active_execution_tracker_basic_lifecycle():
    exec_id = str(uuid4())
    assert not ActiveExecutionTracker.is_active(exec_id)

    ActiveExecutionTracker.add(exec_id)
    assert ActiveExecutionTracker.is_active(exec_id)
    assert exec_id in ActiveExecutionTracker.active_ids()

    ActiveExecutionTracker.remove(exec_id)
    assert not ActiveExecutionTracker.is_active(exec_id)


def test_active_execution_tracker_multithread_concurrency():
    """Verify thread-safe concurrent additions and removals without race conditions."""
    num_threads = 8
    num_ops_per_thread = 100
    all_ids = [str(uuid4()) for _ in range(num_threads * num_ops_per_thread)]

    def worker(ids_slice: list[str]):
        for i_id in ids_slice:
            ActiveExecutionTracker.add(i_id)
            assert ActiveExecutionTracker.is_active(i_id)
        for i_id in ids_slice:
            ActiveExecutionTracker.remove(i_id)

    threads = []
    for i in range(num_threads):
        chunk = all_ids[i * num_ops_per_thread : (i + 1) * num_ops_per_thread]
        t = threading.Thread(target=worker, args=(chunk,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    assert len(ActiveExecutionTracker.active_ids()) == 0


# ==============================================================================
# 3. Tests for TempFileSweeper: sweep_sandbox & Protection Rules
# ==============================================================================


@pytest.mark.asyncio
async def test_sweep_sandbox_skips_active_local_execution(tmp_path: Path):
    sweeper = TempFileSweeper(sandbox_base=tmp_path, grace_period_s=0.0)

    active_id = str(uuid4())
    ActiveExecutionTracker.add(active_id)

    exec_dir = tmp_path / active_id
    exec_dir.mkdir()
    (exec_dir / "sample.pdf").write_bytes(b"dummy")

    # Force mtime to be in the past (e.g. 1 hour ago)
    past_mtime = time.time() - 3600
    os.utime(exec_dir, (past_mtime, past_mtime))

    purged = await sweeper.sweep_sandbox()
    assert purged == 0
    assert exec_dir.exists(), "Active local execution directory must not be swept"


@pytest.mark.asyncio
async def test_sweep_sandbox_skips_active_redis_cluster_lease(tmp_path: Path):
    mock_redis_manager = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.exists = AsyncMock(return_value=1)  # Lease exists in Redis
    mock_redis_manager.get_connection = AsyncMock(return_value=mock_conn)

    sweeper = TempFileSweeper(
        sandbox_base=tmp_path,
        redis_manager=mock_redis_manager,
        grace_period_s=0.0,
    )

    cluster_active_id = str(uuid4())
    exec_dir = tmp_path / cluster_active_id
    exec_dir.mkdir()
    (exec_dir / "doc.pdf").write_bytes(b"cluster_data")

    past_mtime = time.time() - 3600
    os.utime(exec_dir, (past_mtime, past_mtime))

    purged = await sweeper.sweep_sandbox()
    assert purged == 0
    assert exec_dir.exists(), (
        "Directory with active cluster Redis lease must not be swept"
    )
    mock_conn.exists.assert_awaited()


@pytest.mark.asyncio
async def test_sweep_sandbox_skips_directories_within_grace_period(tmp_path: Path):
    # Grace period = 900 seconds (15 minutes)
    sweeper = TempFileSweeper(sandbox_base=tmp_path, grace_period_s=900.0)

    recent_id = str(uuid4())
    exec_dir = tmp_path / recent_id
    exec_dir.mkdir()

    # mtime is 5 minutes ago (< 15 min grace period)
    recent_mtime = time.time() - 300
    os.utime(exec_dir, (recent_mtime, recent_mtime))

    purged = await sweeper.sweep_sandbox()
    assert purged == 0
    assert exec_dir.exists(), "Directory inside grace period must not be swept"


@pytest.mark.asyncio
async def test_sweep_sandbox_purges_orphans_exceeding_grace_period(tmp_path: Path):
    sweeper = TempFileSweeper(sandbox_base=tmp_path, grace_period_s=900.0)

    orphan_id = str(uuid4())
    exec_dir = tmp_path / orphan_id
    exec_dir.mkdir()
    sub_dir = exec_dir / "preprocess"
    sub_dir.mkdir()
    (sub_dir / "page_1.png").write_bytes(b"page content")

    # mtime is 20 minutes ago (> 15 min grace period)
    old_mtime = time.time() - 1200
    os.utime(exec_dir, (old_mtime, old_mtime))

    purged = await sweeper.sweep_sandbox()
    assert purged == 1
    assert not exec_dir.exists(), (
        "Orphaned directory exceeding grace period must be purged"
    )


@pytest.mark.asyncio
async def test_sweep_sandbox_ignores_non_uuid_directories(tmp_path: Path):
    """Folders like .models, models, cache, tessdata must never be touched."""
    sweeper = TempFileSweeper(sandbox_base=tmp_path, grace_period_s=0.0)

    models_dir = tmp_path / ".models"
    models_dir.mkdir()
    weights_file = models_dir / "yoloworld.pt"
    weights_file.write_bytes(b"fake model weights")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    past_mtime = time.time() - 3600
    os.utime(models_dir, (past_mtime, past_mtime))
    os.utime(cache_dir, (past_mtime, past_mtime))

    purged = await sweeper.sweep_sandbox()
    assert purged == 0
    assert models_dir.exists()
    assert weights_file.exists()
    assert cache_dir.exists()


@pytest.mark.asyncio
async def test_sweep_sandbox_safely_removes_unexpected_symlink(tmp_path: Path):
    sweeper = TempFileSweeper(sandbox_base=tmp_path, grace_period_s=0.0)

    outside_dir = tmp_path.parent / "outside_dir"
    outside_dir.mkdir(exist_ok=True)
    outside_file = outside_dir / "host_sensitive.txt"
    outside_file.write_text("HOST SENSITIVE DATA", encoding="utf-8")

    symlink_in_base = tmp_path / "malicious_symlink"
    symlink_in_base.symlink_to(outside_dir, target_is_directory=True)

    await sweeper.sweep_sandbox()
    assert not symlink_in_base.exists()
    assert outside_dir.exists(), "External target must remain intact"
    assert outside_file.read_text(encoding="utf-8") == "HOST SENSITIVE DATA"


# ==============================================================================
# 4. Tests for sweep_replay_payloads
# ==============================================================================


def test_sweep_replay_payloads_retention(tmp_path: Path):
    replay_dir = tmp_path / "replay_dumps"
    replay_dir.mkdir()

    sweeper = TempFileSweeper(replay_dir=replay_dir, replay_retention_hours=24.0)

    now = time.time()

    # 1. Fresh file (created 2 hours ago)
    fresh_file = replay_dir / "fresh.json"
    fresh_file.write_text('{"status": "fresh"}', encoding="utf-8")
    os.utime(fresh_file, (now - 7200, now - 7200))

    # 2. Expired file (created 26 hours ago > 24 hours)
    expired_file = replay_dir / "expired.json"
    expired_file.write_text('{"status": "expired"}', encoding="utf-8")
    os.utime(expired_file, (now - 26 * 3600, now - 26 * 3600))

    # 3. Non-json file (should be ignored)
    log_file = replay_dir / "notes.txt"
    log_file.write_text("notes", encoding="utf-8")
    os.utime(log_file, (now - 30 * 3600, now - 30 * 3600))

    purged = sweeper.sweep_replay_payloads()
    assert purged == 1
    assert fresh_file.exists()
    assert not expired_file.exists()
    assert log_file.exists()


# ==============================================================================
# 5. Tests for Periodic Background Sweeper & Startup Cleanup
# ==============================================================================


@pytest.mark.asyncio
async def test_startup_cleanup_runs_both_sweeps(tmp_path: Path):
    sandbox_base = tmp_path / "sandbox"
    replay_base = tmp_path / "replay"
    sandbox_base.mkdir()
    replay_base.mkdir()

    sweeper = TempFileSweeper(
        sandbox_base=sandbox_base,
        replay_dir=replay_base,
        grace_period_s=0.0,
        replay_retention_hours=0.0,
    )

    orphan_dir = sandbox_base / str(uuid4())
    orphan_dir.mkdir()
    old_time = time.time() - 100
    os.utime(orphan_dir, (old_time, old_time))

    old_replay = replay_base / "payload.json"
    old_replay.write_text("{}", encoding="utf-8")
    os.utime(old_replay, (old_time, old_time))

    await sweeper.startup_cleanup()

    assert not orphan_dir.exists()
    assert not old_replay.exists()


@pytest.mark.asyncio
async def test_run_periodic_sweep_stops_cleanly_on_event(tmp_path: Path):
    sweeper = TempFileSweeper(sandbox_base=tmp_path, grace_period_s=60.0)
    stop_event = asyncio.Event()

    task = asyncio.create_task(
        sweeper.run_periodic_sweep(stop_event, interval_seconds=0.05)
    )

    # Let the sweeper loop run for a couple ticks
    await asyncio.sleep(0.12)
    assert not task.done()

    # Trigger stop
    stop_event.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert task.done()


# ==============================================================================
# 6. Tests for WorkflowManager & ActiveExecutionTracker Integration
# ==============================================================================


@pytest.mark.asyncio
async def test_workflow_manager_lifecycle_tracks_execution():
    from document_ia_infra.redis.model.workflow_execution_message import (
        WorkflowExecutionMessage,
    )
    from document_ia_worker.workflow.workflow_manager import WorkflowManager

    exec_id = str(uuid4())
    msg = WorkflowExecutionMessage(workflow_execution_id=exec_id)

    manager = WorkflowManager(msg, retry_count=0)

    # During start, execution is registered then deregistered on completion/abort
    with (
        patch.object(manager, "_prepare_workflow", new=AsyncMock(return_value=True)),
        patch("document_ia_worker.workflow.workflow_manager.DatabaseManager"),
    ):
        assert not ActiveExecutionTracker.is_active(exec_id)
        await manager.start()
        # After start finishes, it is deregistered in finally block
        assert not ActiveExecutionTracker.is_active(exec_id)


@pytest.mark.asyncio
async def test_workflow_manager_terminal_failure_cleans_sandbox_when_inactive(
    tmp_path: Path,
):
    """When no local attempt is active, watchdog terminal failure cleans the sandbox."""
    from types import SimpleNamespace
    from document_ia_infra.redis.model.workflow_execution_message import (
        WorkflowExecutionMessage,
    )
    from document_ia_worker.workflow.workflow_manager import WorkflowManager

    exec_id = str(uuid4())
    msg = WorkflowExecutionMessage(workflow_execution_id=exec_id)
    manager = WorkflowManager(msg, retry_count=2, is_last_retry=True)

    # Sandbox folder exists, but no local thread in tracker
    sandbox_dir = tmp_path / exec_id
    sandbox_dir.mkdir()
    (sandbox_dir / "temp.pdf").write_bytes(b"data")

    fake_event = SimpleNamespace(
        event_type="WorkflowExecutionStarted",
        event={},
        execution_id=exec_id,
        workflow_id=f"wf-{uuid4()}",
        organization_id=uuid4(),
    )

    class FakeEventStore:
        def __init__(self, _session):
            pass

        async def get_last_event_for_execution_id(self, _id):
            return fake_event

        async def emit_workflow_failed(self, **kwargs):
            pass

    class FakeDbManager:
        def __init__(self, **kwargs):
            pass

        def local_session(self):
            class _Ctx:
                async def __aenter__(self):
                    return MagicMock()

                async def __aexit__(self, *args):
                    return False

            return _Ctx()

        async def dispose_async(self):
            pass

    with (
        patch(
            "document_ia_worker.workflow.workflow_manager.get_execution_sandbox_root",
            return_value=sandbox_dir,
        ),
        patch(
            "document_ia_worker.workflow.workflow_manager.DatabaseManager",
            FakeDbManager,
        ),
        patch(
            "document_ia_worker.workflow.workflow_manager.EventStoreService",
            FakeEventStore,
        ),
        patch.object(manager, "_notify_webhook_execution_finished", new=AsyncMock()),
    ):
        await manager.record_watchdog_terminal_failure("workflow_timeout")

    assert not sandbox_dir.exists(), (
        "Sandbox must be cleaned up on watchdog terminal failure when inactive"
    )


@pytest.mark.asyncio
async def test_workflow_manager_terminal_failure_preserves_sandbox_if_local_attempt_active(
    tmp_path: Path,
):
    """If another local attempt is active, watchdog terminal failure does not remove it or purge its sandbox."""
    from types import SimpleNamespace
    from document_ia_infra.redis.model.workflow_execution_message import (
        WorkflowExecutionMessage,
    )
    from document_ia_worker.workflow.workflow_manager import WorkflowManager

    exec_id = str(uuid4())
    msg = WorkflowExecutionMessage(workflow_execution_id=exec_id)
    manager = WorkflowManager(msg, retry_count=2, is_last_retry=True)

    # Simulate an active thread running
    ActiveExecutionTracker.add(exec_id)
    assert ActiveExecutionTracker.is_active(exec_id)

    sandbox_dir = tmp_path / exec_id
    sandbox_dir.mkdir()
    (sandbox_dir / "temp.pdf").write_bytes(b"data")

    fake_event = SimpleNamespace(
        event_type="WorkflowExecutionStarted",
        event={},
        execution_id=exec_id,
        workflow_id=f"wf-{uuid4()}",
        organization_id=uuid4(),
    )

    class FakeEventStore:
        def __init__(self, _session):
            pass

        async def get_last_event_for_execution_id(self, _id):
            return fake_event

        async def emit_workflow_failed(self, **kwargs):
            pass

    class FakeDbManager:
        def __init__(self, **kwargs):
            pass

        def local_session(self):
            class _Ctx:
                async def __aenter__(self):
                    return MagicMock()

                async def __aexit__(self, *args):
                    return False

            return _Ctx()

        async def dispose_async(self):
            pass

    with (
        patch(
            "document_ia_worker.workflow.workflow_manager.get_execution_sandbox_root",
            return_value=sandbox_dir,
        ),
        patch(
            "document_ia_worker.workflow.workflow_manager.DatabaseManager",
            FakeDbManager,
        ),
        patch(
            "document_ia_worker.workflow.workflow_manager.EventStoreService",
            FakeEventStore,
        ),
        patch.object(manager, "_notify_webhook_execution_finished", new=AsyncMock()),
    ):
        await manager.record_watchdog_terminal_failure("workflow_timeout")

    # The in-flight attempt must NOT be deregistered
    assert ActiveExecutionTracker.is_active(exec_id)
    # The sandbox must NOT be prematurely purged while in-flight
    assert sandbox_dir.exists()


def test_active_execution_tracker_reference_counting_overlapping_retries():
    """Verify reference counting when multiple attempts/threads overlap."""
    exec_id = str(uuid4())
    assert not ActiveExecutionTracker.is_active(exec_id)

    # First attempt starts
    ActiveExecutionTracker.add(exec_id)
    assert ActiveExecutionTracker.is_active(exec_id)
    assert ActiveExecutionTracker.active_ids() == {exec_id}

    # Second retry attempt starts concurrently before first terminates
    ActiveExecutionTracker.add(exec_id)
    assert ActiveExecutionTracker.is_active(exec_id)

    # First attempt finishes and decrements count
    ActiveExecutionTracker.remove(exec_id)
    assert ActiveExecutionTracker.is_active(exec_id), (
        "Execution must remain active while second attempt is still running"
    )
    assert ActiveExecutionTracker.active_ids() == {exec_id}

    # Second attempt finishes
    ActiveExecutionTracker.remove(exec_id)
    assert not ActiveExecutionTracker.is_active(exec_id)
    assert len(ActiveExecutionTracker.active_ids()) == 0


@pytest.mark.asyncio
async def test_sweep_sandbox_and_replay_refuse_symlinked_root_dirs(tmp_path: Path):
    """If sandbox_base or replay_dir is a symlink, sweeper must refuse to sweep and delete nothing."""
    outside_sandbox = tmp_path / "outside_sandbox"
    outside_sandbox.mkdir()
    outside_uuid_dir = outside_sandbox / str(uuid4())
    outside_uuid_dir.mkdir()
    (outside_uuid_dir / "secret.pdf").write_bytes(b"victim doc")
    past = time.time() - 3600
    os.utime(outside_uuid_dir, (past, past))

    outside_replay = tmp_path / "outside_replay"
    outside_replay.mkdir()
    outside_json = outside_replay / "expired.json"
    outside_json.write_text('{"secret": "data"}', encoding="utf-8")
    os.utime(outside_json, (past, past))

    symlinked_base = tmp_path / "sym_sandbox"
    symlinked_base.symlink_to(outside_sandbox, target_is_directory=True)

    symlinked_replay = tmp_path / "sym_replay"
    symlinked_replay.symlink_to(outside_replay, target_is_directory=True)

    sweeper = TempFileSweeper(
        sandbox_base=symlinked_base,
        replay_dir=symlinked_replay,
        grace_period_s=0.0,
        replay_retention_hours=0.01,
    )

    purged_sandboxes = await sweeper.sweep_sandbox()
    assert purged_sandboxes == 0
    assert outside_uuid_dir.exists(), (
        "Outside directory must not be deleted through symlink"
    )
    assert (outside_uuid_dir / "secret.pdf").exists()

    purged_replays = sweeper.sweep_replay_payloads()
    assert purged_replays == 0
    assert outside_json.exists(), (
        "Outside replay payload must not be deleted through symlink"
    )


@pytest.mark.asyncio
async def test_sweep_sandbox_does_not_increment_purged_count_on_cleanup_failure(
    tmp_path: Path,
):
    """If safe_cleanup_directory fails, purged_count must not be incremented."""
    sweeper = TempFileSweeper(sandbox_base=tmp_path, grace_period_s=0.0)

    orphan_id = str(uuid4())
    exec_dir = tmp_path / orphan_id
    exec_dir.mkdir()
    past = time.time() - 3600
    os.utime(exec_dir, (past, past))

    with patch(
        "document_ia_worker.core.temp_file_sweeper.safe_cleanup_directory",
        return_value=False,
    ) as mock_cleanup:
        purged = await sweeper.sweep_sandbox()
        assert purged == 0
        mock_cleanup.assert_called_once_with(exec_dir, sandbox_root=tmp_path)


def test_sweeper_uses_settings_replay_retention_hours(monkeypatch: pytest.MonkeyPatch):
    """TempFileSweeper must read llm_settings.OPENAI_REPLAY_RETENTION_HOURS by default."""
    from document_ia_worker.workflow.step.llm_extract_document.settings import (
        settings as llm_settings,
    )

    monkeypatch.setattr(llm_settings, "OPENAI_REPLAY_RETENTION_HOURS", 48.0)
    sweeper = TempFileSweeper()
    assert sweeper.replay_retention_hours == 48.0

    custom_sweeper = TempFileSweeper(replay_retention_hours=12.0)
    assert custom_sweeper.replay_retention_hours == 12.0
