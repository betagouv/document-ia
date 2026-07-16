import copy
from datetime import datetime, UTC
from uuid import uuid4

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
            "file_info": {"s3_key": "SECRET"},
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
        assert source.event["file_info"] == {"s3_key": "SECRET"}
        assert source.event["metadata"] == {"user": "john"}

    def test_returned_copy_is_anonymized_and_independent(self):
        source = _make_started_event()

        replica = ReplicateAnalytics._to_replicated_event(source)

        # Sensitive fields cleared, non-sensitive fields preserved.
        assert replica.event["file_info"] == {}
        assert replica.event["metadata"] == {}
        assert replica.event["keep"] == 42
        assert replica.anonymization_status == AnonymizationStatus.DONE.value
        # Identity columns preserved for ON CONFLICT (id) dedup.
        assert replica.id == source.id
        assert replica.created_at == source.created_at

        # The replica payload is a distinct object graph from the source.
        assert replica.event is not source.event
        assert replica.event["file_info"] is not source.event["file_info"]

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
