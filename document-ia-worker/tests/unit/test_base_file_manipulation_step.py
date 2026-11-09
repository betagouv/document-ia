"""Unit tests for BaseFileManipulationStep cleanup gating on aborted attempts."""

from pathlib import Path
from uuid import uuid4

import pytest

from document_ia_infra.redis.progress_tracker import (
    ProgressTracker,
    current_progress_tracker,
)
from document_ia_worker.workflow.step.base_file_manipulation_step import (
    BaseFileManipulationStep,
)


class _ExecutionContext:
    def __init__(self, execution_id: str):
        self.execution_id = execution_id


class _CleanupStep(BaseFileManipulationStep):
    """Probe concrète exposant uniquement le comportement de nettoyage."""

    async def execute(self):
        return ("result", None)

    def get_context_result_key(self) -> str:
        return "probe"


@pytest.mark.asyncio
async def test_aborted_attempt_does_not_delete_shared_tmp_dir():
    """Une tentative avortée ne supprime pas les fichiers du répertoire partagé."""
    exec_id = f"exec-{uuid4()}"
    step = _CleanupStep(_ExecutionContext(exec_id))

    tmp_dir = Path("/tmp/document_ia_worker.tmp") / exec_id
    tmp_dir.mkdir(parents=True, exist_ok=True)
    probe_file = tmp_dir / "download.pdf"
    probe_file.write_bytes(b"data")

    tracker = ProgressTracker(msg_id="m", max_processing_time_s=1.0)
    tracker.abort("step_timeout")
    token = current_progress_tracker.set(tracker)
    try:
        await step.cleanup(is_last_cleanup=False)
    finally:
        current_progress_tracker.reset(token)

    assert probe_file.exists()
    assert tmp_dir.exists()


@pytest.mark.asyncio
async def test_non_aborted_cleanup_still_removes_tmp_files():
    """Le comportement nominal est préservé : nettoyage local même si ce n'est pas le dernier essai."""
    exec_id = f"exec-{uuid4()}"
    step = _CleanupStep(_ExecutionContext(exec_id))

    tmp_dir = Path("/tmp/document_ia_worker.tmp") / exec_id
    tmp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_dir / "input.pdf").write_bytes(b"data")

    await step.cleanup(is_last_cleanup=False)

    assert not tmp_dir.exists()
