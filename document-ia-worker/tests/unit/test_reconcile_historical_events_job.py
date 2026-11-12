import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from document_ia_infra.data.event.dto.anonymization_enum import AnonymizationStatus
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.entity.event_entity import EventEntity
from document_ia_task_scheduler.task.reconcile_historical_events.job import (
    ReconcileHistoricalEventsJob,
)
from document_ia_task_scheduler.task.reconcile_historical_events.main import (
    async_main,
    parse_args,
)


def _make_event(
    status: str = AnonymizationStatus.DONE.value,
    event_type: str = EventType.WORKFLOW_EXECUTION_STARTED.value,
) -> EventEntity:
    return EventEntity(
        id=uuid4(),
        organization_id=uuid4(),
        workflow_id="wf_hist",
        execution_id="exec_hist",
        created_at=datetime.now(timezone.utc),
        event_type=event_type,
        event={
            "file_url": "https://secret/doc.pdf",
            "s3_file_info": {"filename": "doc.pdf"},
            "metadata": {"user": "bob"},
        },
        anonymization_status=status,
    )


@pytest.mark.asyncio
async def test_reconcile_job_nominal(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO)

    event1 = _make_event(status=AnonymizationStatus.DONE.value)
    event2 = _make_event(status=AnonymizationStatus.ERROR.value)

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_db = MagicMock()
    mock_db.local_session.return_value.__aenter__.return_value = mock_session
    mock_db.dispose_async = AsyncMock()

    with (
        patch(
            "document_ia_task_scheduler.task.reconcile_historical_events.job.DatabaseManager",
            return_value=mock_db,
        ),
        patch(
            "document_ia_task_scheduler.task.reconcile_historical_events.job.EventRepository"
        ) as mock_repo_class,
    ):
        from document_ia_infra.data.event.repository.event import EventRepository

        mock_repo_class.anonymize_payload = EventRepository.anonymize_payload
        mock_repo = mock_repo_class.return_value
        mock_repo.count_events_by_statuses = AsyncMock(return_value=2)
        mock_repo.get_events_by_cursor = AsyncMock(side_effect=[[event1, event2], []])

        job = ReconcileHistoricalEventsJob(
            batch_size=2, pause_seconds=0.0, dry_run=False
        )
        stats = await job.run(target="main")

        assert stats["main"]["total"] == 2
        assert stats["main"]["success"] == 2
        assert stats["main"]["errors"] == 0
        assert mock_session.commit.called

        # Vérifier que les événements ont été anonymisés
        assert event1.event["s3_file_info"] is None
        assert event1.event["file_url"] is None
        assert event1.anonymization_status == AnonymizationStatus.DONE.value
        assert event2.anonymization_status == AnonymizationStatus.DONE.value

        # Vérifier l'affichage du log de progression
        assert any("[Traitement MAIN] Lot 1/1" in r.message for r in caplog.records)
        assert any("Succès: 2" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_reconcile_job_dry_run():
    event1 = _make_event()

    mock_session = AsyncMock()
    mock_db = MagicMock()
    mock_db.local_session.return_value.__aenter__.return_value = mock_session
    mock_db.dispose_async = AsyncMock()

    with (
        patch(
            "document_ia_task_scheduler.task.reconcile_historical_events.job.DatabaseManager",
            return_value=mock_db,
        ),
        patch(
            "document_ia_task_scheduler.task.reconcile_historical_events.job.EventRepository"
        ) as mock_repo_class,
    ):
        mock_repo = mock_repo_class.return_value
        mock_repo.count_events_by_statuses = AsyncMock(return_value=1)
        mock_repo.get_events_by_cursor = AsyncMock(side_effect=[[event1], []])

        job = ReconcileHistoricalEventsJob(
            batch_size=10, pause_seconds=0.0, dry_run=True
        )
        stats = await job.run(target="main")

        assert stats["main"]["total"] == 1
        assert stats["main"]["success"] == 1
        assert stats["main"]["errors"] == 0
        # En mode dry-run, commit ne doit JAMAIS être appelé
        mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_job_both_targets():
    mock_session = AsyncMock()
    mock_db = MagicMock()
    mock_db.local_session.return_value.__aenter__.return_value = mock_session
    mock_db.dispose_async = AsyncMock()

    with (
        patch(
            "document_ia_task_scheduler.task.reconcile_historical_events.job.DatabaseManager",
            return_value=mock_db,
        ),
        patch(
            "document_ia_task_scheduler.task.reconcile_historical_events.job.EventRepository"
        ) as mock_repo_class,
    ):
        mock_repo = mock_repo_class.return_value
        mock_repo.count_events_by_statuses = AsyncMock(return_value=0)

        job = ReconcileHistoricalEventsJob(batch_size=100, pause_seconds=0.0)
        stats = await job.run(target="both")

        assert "main" in stats
        assert "analytics" in stats
        assert stats["main"]["total"] == 0
        assert stats["analytics"]["total"] == 0


@pytest.mark.asyncio
async def test_reconcile_job_batch_failure_fallback_unitary():
    event_ok = _make_event()
    event_err = _make_event()

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_db = MagicMock()
    mock_db.local_session.return_value.__aenter__.return_value = mock_session
    mock_db.dispose_async = AsyncMock()

    with (
        patch(
            "document_ia_task_scheduler.task.reconcile_historical_events.job.DatabaseManager",
            return_value=mock_db,
        ),
        patch(
            "document_ia_task_scheduler.task.reconcile_historical_events.job.EventRepository"
        ) as mock_repo_class,
    ):
        from document_ia_infra.data.event.repository.event import EventRepository

        mock_repo_class.anonymize_payload = EventRepository.anonymize_payload
        mock_repo = mock_repo_class.return_value
        mock_repo.count_events_by_statuses = AsyncMock(return_value=2)
        mock_repo.get_events_by_cursor = AsyncMock(
            side_effect=[[event_ok, event_err], []]
        )

        # 1er commit (lot entier) -> échoue
        # 2e commit (event_ok) -> réussit
        # 3e commit (event_err) -> échoue
        # 4e commit (marquage ERROR pour event_err) -> réussit
        mock_session.commit.side_effect = [
            RuntimeError("Batch commit failed"),
            None,
            RuntimeError("Unitary commit failed for event_err"),
            None,
        ]

        job = ReconcileHistoricalEventsJob(
            batch_size=2, pause_seconds=0.0, dry_run=False
        )
        stats = await job.run(target="main")

        assert stats["main"]["total"] == 2
        assert stats["main"]["success"] == 1
        assert stats["main"]["errors"] == 1
        assert mock_session.rollback.call_count >= 2


def test_cli_parse_args():
    args = parse_args(["--target", "analytics", "--batch-size", "500", "--dry-run"])
    assert args.target == "analytics"
    assert args.batch_size == 500
    assert args.dry_run is True
    assert args.pause == 0.05


@pytest.mark.asyncio
async def test_cli_async_main():
    with patch(
        "document_ia_task_scheduler.task.reconcile_historical_events.main.ReconcileHistoricalEventsJob"
    ) as mock_job_class:
        mock_job = mock_job_class.return_value
        mock_job.run = AsyncMock(
            return_value={"main": {"errors": 0}, "analytics": {"errors": 0}}
        )

        args = parse_args(["--target", "main"])
        code = await async_main(args)
        assert code == 0

        # Erreurs détectées -> code retour 1
        mock_job.run = AsyncMock(return_value={"main": {"errors": 1}})
        code_err = await async_main(args)
        assert code_err == 1


@pytest.mark.asyncio
async def test_reconcile_job_survives_expired_attributes_on_fallback():
    """Verify that rollback expiring entities does not crash unitary fallback or cursor advance."""
    ev1 = _make_event(status=AnonymizationStatus.DONE.value)
    ev2 = _make_event(status=AnonymizationStatus.ERROR.value)

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_db = MagicMock()
    mock_db.local_session.return_value.__aenter__.return_value = mock_session
    mock_db.dispose_async = AsyncMock()

    with (
        patch(
            "document_ia_task_scheduler.task.reconcile_historical_events.job.DatabaseManager",
            return_value=mock_db,
        ),
        patch(
            "document_ia_task_scheduler.task.reconcile_historical_events.job.EventRepository"
        ) as mock_repo_class,
    ):
        from document_ia_infra.data.event.repository.event import EventRepository

        mock_repo_class.anonymize_payload = EventRepository.anonymize_payload
        mock_repo = mock_repo_class.return_value
        mock_repo.count_events_by_statuses = AsyncMock(return_value=2)
        mock_repo.get_events_by_cursor = AsyncMock(side_effect=[[ev1, ev2], []])

        commit_count = 0

        async def fake_commit():
            nonlocal commit_count
            commit_count += 1
            if commit_count == 1:
                # Simulate attributes becoming inaccessible on ev1 & ev2 after rollback
                for ev in (ev1, ev2):
                    ev.__dict__.clear()
                raise RuntimeError("Batch commit failed")

        mock_session.commit = AsyncMock(side_effect=fake_commit)

        job = ReconcileHistoricalEventsJob(batch_size=2, pause_seconds=0.0)
        # Must execute without raising MissingGreenlet / KeyError / RuntimeError on ev.id
        stats = await job.run(target="main")
        assert stats["main"]["success"] == 2
        assert stats["main"]["errors"] == 0


async def test_reconcile_job_analytics_not_configured_returns_zero(
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.WARNING)

    with patch(
        "document_ia_task_scheduler.task.reconcile_historical_events.job.replicate_analytics_settings"
    ) as mock_settings:
        mock_settings.is_configured.return_value = False

        job = ReconcileHistoricalEventsJob(batch_size=10, pause_seconds=0.0)
        stats = await job.run(target="analytics")

        assert stats["analytics"] == {
            "total": 0,
            "processed": 0,
            "success": 0,
            "errors": 0,
        }
        assert any(
            "[ANALYTICS] Base analytique non configurée, réconciliation ignorée."
            in r.message
            for r in caplog.records
        )


@pytest.mark.asyncio
async def test_reconcile_job_analytics_includes_pending_status():
    mock_session = AsyncMock()
    mock_db = MagicMock()
    mock_db.local_session.return_value.__aenter__.return_value = mock_session
    mock_db.dispose_async = AsyncMock()

    with (
        patch(
            "document_ia_task_scheduler.task.reconcile_historical_events.job.replicate_analytics_settings"
        ) as mock_settings,
        patch(
            "document_ia_task_scheduler.task.reconcile_historical_events.job.DatabaseManager",
            return_value=mock_db,
        ),
        patch(
            "document_ia_task_scheduler.task.reconcile_historical_events.job.EventRepository"
        ) as mock_repo_class,
    ):
        mock_settings.is_configured.return_value = True
        mock_repo = mock_repo_class.return_value
        mock_repo.count_events_by_statuses = AsyncMock(return_value=0)

        job = ReconcileHistoricalEventsJob(batch_size=10, pause_seconds=0.0)
        await job.run(target="analytics")

        # Verify count_events_by_statuses called with PENDING, DONE, ERROR
        statuses_called = mock_repo.count_events_by_statuses.call_args[0][0]
        assert "PENDING" in statuses_called
        assert "DONE" in statuses_called
        assert "ERROR" in statuses_called
