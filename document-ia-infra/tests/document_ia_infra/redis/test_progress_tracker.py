"""Unit tests for ProgressTracker."""

import time
from document_ia_infra.redis.progress_tracker import (
    ProgressTracker,
    current_progress_tracker,
    get_current_progress_tracker,
    record_step_progress,
)


def test_progress_tracker_init():
    tracker = ProgressTracker("1-0", max_processing_time_s=10.0, step_progress_timeout_s=5.0)
    assert tracker.msg_id == "1-0"
    assert tracker.max_processing_time_s == 10.0
    assert tracker.step_progress_timeout_s == 5.0
    assert tracker.is_healthy()
    assert not tracker.is_aborted
    assert tracker.abort_reason is None


def test_progress_tracker_step_timeout():
    tracker = ProgressTracker("1-0", max_processing_time_s=10.0, step_progress_timeout_s=0.05)
    assert tracker.is_healthy()
    time.sleep(0.06)
    assert not tracker.is_healthy()
    assert tracker.check_timeout_reason() == "step_timeout"


def test_progress_tracker_step_progress_keeps_healthy():
    tracker = ProgressTracker("1-0", max_processing_time_s=10.0, step_progress_timeout_s=0.1)
    time.sleep(0.06)
    tracker.record_step("step_1")
    assert tracker.is_healthy()
    assert tracker.current_step == "step_1"
    time.sleep(0.06)
    tracker.record_step("step_2")
    assert tracker.is_healthy()
    assert tracker.current_step == "step_2"


def test_progress_tracker_max_processing_time_timeout():
    tracker = ProgressTracker("1-0", max_processing_time_s=0.1, step_progress_timeout_s=1.0)
    assert tracker.is_healthy()
    time.sleep(0.06)
    tracker.record_step("step_1")
    assert tracker.is_healthy()
    time.sleep(0.06)
    # Total elapsed > 0.1s even though step progress was made
    assert not tracker.is_healthy()
    assert tracker.check_timeout_reason() == "workflow_timeout"


def test_progress_tracker_abort():
    tracker = ProgressTracker("1-0", max_processing_time_s=10.0, step_progress_timeout_s=5.0)
    assert tracker.is_healthy()
    tracker.abort("custom_reason")
    assert not tracker.is_healthy()
    assert tracker.is_aborted
    assert tracker.abort_reason == "custom_reason"


def test_contextvar_helpers():
    tracker = ProgressTracker("1-0", max_processing_time_s=10.0, step_progress_timeout_s=5.0)
    assert get_current_progress_tracker() is None

    token = current_progress_tracker.set(tracker)
    try:
        assert get_current_progress_tracker() is tracker
        record_step_progress("step_alpha")
        assert tracker.current_step == "step_alpha"
    finally:
        current_progress_tracker.reset(token)

    assert get_current_progress_tracker() is None
