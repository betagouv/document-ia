import copy
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from document_ia_infra.data.event.dto.anonymization_enum import AnonymizationStatus
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.entity.event_entity import EventEntity
from document_ia_infra.data.organization.entity.organization import OrganizationEntity
from document_ia_task_scheduler.task.replicate_analytics.job import ReplicateAnalytics


def _make_started_event() -> EventEntity:
    return EventEntity(
        id=uuid4(),
        organization_id=uuid4(),
        workflow_id="wf",
        execution_id="ex",
        created_at=datetime.now(UTC),
        event_type=EventType.WORKFLOW_EXECUTION_STARTED.value,
        event={
            "s3_file_info": {"s3_key": "SECRET"},
            "metadata": {"user": "john"},
            "keep": 42,
        },
    )


class TestToReplicatedRow:
    def test_source_event_is_not_mutated(self):
        source = _make_started_event()
        source_snapshot = copy.deepcopy(source.event)

        ReplicateAnalytics._to_replicated_event(source)

        # The source payload (including nested dicts) is left untouched.
        assert source.event == source_snapshot
        assert source.event["s3_file_info"] == {"s3_key": "SECRET"}
        assert source.event["metadata"] == {"user": "john"}

    def test_returned_copy_is_anonymized_and_independent(self):
        source = _make_started_event()

        replica = ReplicateAnalytics._to_replicated_event(source)

        # Sensitive fields cleared, non-sensitive fields preserved.
        assert replica.event["s3_file_info"] is None
        assert replica.event.get("file_url") is None
        assert replica.event["metadata"] == {}
        assert replica.event["keep"] == 42
        assert replica.anonymization_status == AnonymizationStatus.DONE.value
        # Identity columns preserved for ON CONFLICT (id) dedup.
        assert replica.id == source.id
        assert replica.created_at == source.created_at

        # The replica payload is a distinct object graph from the source.
        assert replica.event is not source.event
        assert replica.event["metadata"] is not source.event["metadata"]

    def test_mutating_replica_does_not_affect_source(self):
        source = _make_started_event()

        replica = ReplicateAnalytics._to_replicated_event(source)
        replica.event["keep"] = "CHANGED"

        assert source.event["keep"] == 42


class TestToReplicatedOrganization:
    def test_source_organization_is_not_mutated(self):
        source = OrganizationEntity(
            id=uuid4(),
            contact_email="a@b.c",
            name="Org",
            platform_role="Standard",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        replica = ReplicateAnalytics._to_replicated_organization(source)
        # Mutating the replica must not leak back to the source entity.
        replica.name = "CHANGED"

        assert replica is not source
        assert source.name == "Org"
        assert replica.id == source.id


class TestReplicateEvents:
    @pytest.mark.asyncio
    async def test_replicate_events_aborts_on_bulk_insert_failure(self):
        source_manager = MagicMock()
        dest_manager = MagicMock()
        source_session = AsyncMock()
        dest_session = AsyncMock()
        source_manager.local_session.return_value.__aenter__.return_value = (
            source_session
        )
        dest_manager.local_session.return_value.__aenter__.return_value = dest_session

        ev1 = _make_started_event()
        ev2 = _make_started_event()

        with (
            patch(
                "document_ia_task_scheduler.task.replicate_analytics.job.EventRepository"
            ) as mock_repo_class,
            patch(
                "document_ia_task_scheduler.task.replicate_analytics.job.replicate_analytics_settings"
            ) as mock_settings,
        ):
            mock_settings.EVENT_BATCH_SIZE = 2
            mock_repo = mock_repo_class.return_value
            mock_repo.get_replication_cursor = AsyncMock(return_value=None)
            # Returns batch of 2 events
            mock_repo.get_events_created_after = AsyncMock(return_value=[ev1, ev2])
            # Bulk insert fails
            mock_repo.bulk_insert_events = AsyncMock(
                side_effect=RuntimeError("Insert failed")
            )

            job = ReplicateAnalytics()
            await job._replicate_events(source_manager, dest_manager)

            # Bulk insert was called once and failed, loop broke immediately
            mock_repo.bulk_insert_events.assert_called_once()
            # get_events_created_after should not have been called a second time
            mock_repo.get_events_created_after.assert_called_once()
