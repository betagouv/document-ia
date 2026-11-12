import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from document_ia_infra.data.event.dto.anonymization_enum import AnonymizationStatus
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.entity.event_entity import EventEntity
from document_ia_task_scheduler.task.remove_ppi.job import RemovePPI


def _make_event(
    status: str = AnonymizationStatus.PENDING.value,
    event_type: str = EventType.WORKFLOW_EXECUTION_COMPLETED.value,
) -> EventEntity:
    return EventEntity(
        id=uuid4(),
        organization_id=uuid4(),
        workflow_id="wf_test",
        execution_id="exec_test",
        created_at=datetime.now(timezone.utc),
        event_type=event_type,
        event={
            "final_result": {"secret": "data"},
            "output_summary": {"summary": "sum"},
        },
        anonymization_status=status,
    )


@pytest.mark.asyncio
async def test_remove_ppi_job_batches_and_emits_metrics(
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)

    event1 = _make_event(status=AnonymizationStatus.PENDING.value)
    event2 = _make_event(status=AnonymizationStatus.ERROR.value)

    mock_session = AsyncMock()
    mock_db_manager = MagicMock()
    mock_db_manager.return_value.local_session.return_value.__aenter__.return_value = (
        mock_session
    )

    with (
        patch(
            "document_ia_task_scheduler.task.remove_ppi.job.DatabaseManager",
            mock_db_manager,
        ),
        patch(
            "document_ia_task_scheduler.task.remove_ppi.job.EventRepository"
        ) as mock_repo_class,
        patch(
            "document_ia_task_scheduler.task.remove_ppi.job.remove_ppi_settings"
        ) as mock_settings,
    ):
        mock_settings.EVENT_STORE_PPI_RETENTION_DAYS = 7
        mock_settings.EVENT_STORE_PPI_BATCH_SIZE = 2

        mock_repo = mock_repo_class.return_value
        mock_repo.get_oldest_pending_event_age_seconds = AsyncMock(return_value=123.45)
        # First call returns 2 events (full batch), second call returns 0 events (empty)
        mock_repo.get_events_to_anonymize = AsyncMock(
            side_effect=[[event1, event2], []]
        )
        mock_repo.anonymize_event = AsyncMock()
        mock_repo.save_failed_anonymization = AsyncMock()

        job = RemovePPI()
        await job._internal_execute()

        # Check age metric was logged
        assert any(
            "event_purge operation=lag outcome=oldest_pending_age_seconds value=123.45"
            in record.message
            for record in caplog.records
        )
        # Check success metric was logged
        assert any(
            "event_purge operation=purge outcome=success value=2" in record.message
            for record in caplog.records
        )
        # Check error metric was logged
        assert any(
            "event_purge operation=purge outcome=error value=0" in record.message
            for record in caplog.records
        )

        assert mock_repo.anonymize_event.call_count == 2
        mock_repo.save_failed_anonymization.assert_not_called()


@pytest.mark.asyncio
async def test_remove_ppi_job_handles_individual_errors_resiliently(
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)

    event_ok = _make_event(status=AnonymizationStatus.PENDING.value)
    event_fail = _make_event(status=AnonymizationStatus.ERROR.value)

    mock_session = AsyncMock()
    mock_db_manager = MagicMock()
    mock_db_manager.return_value.local_session.return_value.__aenter__.return_value = (
        mock_session
    )

    with (
        patch(
            "document_ia_task_scheduler.task.remove_ppi.job.DatabaseManager",
            mock_db_manager,
        ),
        patch(
            "document_ia_task_scheduler.task.remove_ppi.job.EventRepository"
        ) as mock_repo_class,
        patch(
            "document_ia_task_scheduler.task.remove_ppi.job.remove_ppi_settings"
        ) as mock_settings,
    ):
        mock_settings.EVENT_STORE_PPI_RETENTION_DAYS = 7
        mock_settings.EVENT_STORE_PPI_BATCH_SIZE = 10

        mock_repo = mock_repo_class.return_value
        mock_repo.get_oldest_pending_event_age_seconds = AsyncMock(return_value=None)
        # Returns one batch with 2 events (< batch_size 10, so loop terminates after 1 iteration)
        mock_repo.get_events_to_anonymize = AsyncMock(
            return_value=[event_ok, event_fail]
        )

        async def anonymize_side_effect(ev: EventEntity):
            if ev.id == event_fail.id:
                raise RuntimeError("Database connection interrupted for this row")

        mock_repo.anonymize_event = AsyncMock(side_effect=anonymize_side_effect)
        mock_repo.save_failed_anonymization = AsyncMock()

        job = RemovePPI()
        await job._internal_execute()

        # Both events were attempted
        assert mock_repo.anonymize_event.call_count == 2
        # Failed event was recorded as failed
        mock_repo.save_failed_anonymization.assert_called_once_with(event_fail.id)

        # Check outcome metrics
        assert any(
            "event_purge operation=lag outcome=oldest_pending_age_seconds value=0.00"
            in record.message
            for record in caplog.records
        )
        assert any(
            "event_purge operation=purge outcome=success value=1" in record.message
            for record in caplog.records
        )
        assert any(
            "event_purge operation=purge outcome=error value=1" in record.message
            for record in caplog.records
        )


@pytest.mark.asyncio
async def test_remove_ppi_job_emits_lag_after_purge_loop():
    call_order = []

    mock_session = AsyncMock()
    mock_db_manager = MagicMock()
    mock_db_manager.return_value.local_session.return_value.__aenter__.return_value = (
        mock_session
    )

    with (
        patch(
            "document_ia_task_scheduler.task.remove_ppi.job.DatabaseManager",
            mock_db_manager,
        ),
        patch(
            "document_ia_task_scheduler.task.remove_ppi.job.EventRepository"
        ) as mock_repo_class,
        patch(
            "document_ia_task_scheduler.task.remove_ppi.job.remove_ppi_settings"
        ) as mock_settings,
    ):
        mock_settings.EVENT_STORE_PPI_RETENTION_DAYS = 7
        mock_settings.EVENT_STORE_PPI_BATCH_SIZE = 10

        event = _make_event()
        mock_repo = mock_repo_class.return_value

        async def fake_anonymize(ev):
            call_order.append("anonymize")

        async def fake_get_lag(before_date=None):
            call_order.append("get_lag")
            return 42.0

        mock_repo.get_events_to_anonymize = AsyncMock(side_effect=[[event], []])
        mock_repo.anonymize_event = AsyncMock(side_effect=fake_anonymize)
        mock_repo.get_oldest_pending_event_age_seconds = AsyncMock(
            side_effect=fake_get_lag
        )

        job = RemovePPI()
        await job._internal_execute()

        assert call_order == ["anonymize", "get_lag"], (
            "Lag metric must be computed AFTER the purge loop"
        )


@pytest.mark.asyncio
async def test_remove_ppi_job_survives_sqlalchemy_session_rollback_expiration(
    caplog: pytest.LogCaptureFixture,
):
    """Verify RemovePPI does not raise MissingGreenlet when an event's attributes expire."""
    caplog.set_level(logging.INFO)

    class ExpiringEvent:
        def __init__(self, uid):
            self._uid = uid
            self.expired = False

        @property
        def id(self):
            if self.expired:
                raise RuntimeError("MissingGreenlet: attribute expired after rollback")
            return self._uid

    ev1 = ExpiringEvent(uuid4())
    ev2 = ExpiringEvent(uuid4())

    mock_session = AsyncMock()
    mock_db_manager = MagicMock()
    mock_db_manager.return_value.local_session.return_value.__aenter__.return_value = (
        mock_session
    )

    with (
        patch(
            "document_ia_task_scheduler.task.remove_ppi.job.DatabaseManager",
            mock_db_manager,
        ),
        patch(
            "document_ia_task_scheduler.task.remove_ppi.job.EventRepository"
        ) as mock_repo_class,
        patch(
            "document_ia_task_scheduler.task.remove_ppi.job.remove_ppi_settings"
        ) as mock_settings,
    ):
        mock_settings.EVENT_STORE_PPI_RETENTION_DAYS = 7
        mock_settings.EVENT_STORE_PPI_BATCH_SIZE = 10

        mock_repo = mock_repo_class.return_value
        mock_repo.get_oldest_pending_event_age_seconds = AsyncMock(return_value=0.0)
        mock_repo.get_events_to_anonymize = AsyncMock(return_value=[ev1, ev2])

        async def failing_anonymize(ev):
            # Simulate rollback expiring attributes on ev
            ev.expired = True
            raise RuntimeError("Database deadlock during commit")

        mock_repo.anonymize_event = AsyncMock(side_effect=failing_anonymize)
        mock_repo.save_failed_anonymization = AsyncMock()

        job = RemovePPI()
        # Must not raise MissingGreenlet / RuntimeError from ev.id
        await job._internal_execute()

        assert mock_repo.anonymize_event.call_count == 2
        assert mock_repo.save_failed_anonymization.call_count == 2
        mock_repo.save_failed_anonymization.assert_any_call(ev1._uid)
        mock_repo.save_failed_anonymization.assert_any_call(ev2._uid)
