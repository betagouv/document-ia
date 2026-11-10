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
        mock_repo.save_failed_anonymization.assert_called_once_with(event_fail)

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
