"""
Unit tests for EventStoreRepository.

This module contains comprehensive unit tests for the event store repository,
testing all CRUD operations and event stream functionality.
"""

from datetime import datetime, timedelta, timezone, UTC
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.event.dto.anonymization_enum import AnonymizationStatus
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.entity.event_entity import EventEntity
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_infra.exception.processing_aborted_exception import (
    ProcessingAbortedException,
)
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.redis.progress_tracker import (
    ProgressTracker,
    current_progress_tracker,
)


@pytest.fixture
def mock_session():
    """Create a mock async database session."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def event_repository(mock_session):
    """Create an EventRepository instance with mock session."""
    return EventRepository(mock_session)


@pytest.fixture
def sample_event_data():
    """Sample event data for testing."""
    return {
        "event_id": str(uuid4()),
        "organization_id": str(uuid4()),
        "workflow_id": "test_workflow_001",
        "execution_id": "test_execution_001",
        "created_at": datetime.now().isoformat(),
        "event_type": "WorkflowExecutionStarted",
        "file_info": {"filename": "test.pdf", "size": 1024},
        "metadata": {"source": "test"},
    }


class TestEventRepository:
    """Test cases for EventRepository."""

    async def test_put_event_success(
        self, event_repository, mock_session, sample_event_data
    ):
        """Test successful event storage."""
        # Arrange
        mock_session.flush.return_value = None
        mock_session.refresh.return_value = None

        # Mock the refresh to set the id
        def mock_refresh(obj):
            obj.id = uuid4()
            obj.created_at = datetime.now(UTC)

        mock_session.refresh.side_effect = mock_refresh

        # Act
        result = await event_repository.put_event(
            workflow_id="test_workflow_001",
            organization_id=uuid4(),
            execution_id="test_execution_001",
            event_type="WorkflowExecutionStarted",
            event_data=sample_event_data,
        )

        # Assert
        assert isinstance(result, EventDTO)
        assert result.workflow_id == "test_workflow_001"
        assert result.execution_id == "test_execution_001"
        assert result.event_type == "WorkflowExecutionStarted"
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()
        mock_session.refresh.assert_called_once()

    async def test_put_event_refuses_to_commit_when_processing_aborted(
        self, event_repository, mock_session
    ):
        """A write fences at the persistence boundary once the watchdog aborts the attempt.

        ``put_event`` commits internally, so the worker's own ``is_aborted`` guard runs
        too late; the check must happen here, immediately before the commit.
        """
        tracker = ProgressTracker(msg_id="msg-1", max_processing_time_s=1.0)
        tracker.abort("step_timeout")
        token = current_progress_tracker.set(tracker)
        try:
            with pytest.raises(ProcessingAbortedException):
                await event_repository.put_event(
                    workflow_id="test_workflow_001",
                    organization_id=uuid4(),
                    execution_id="test_execution_001",
                    event_type=EventType.WORKFLOW_EXECUTION_COMPLETED.value,
                    event_data={},
                )
        finally:
            current_progress_tracker.reset(token)

        mock_session.commit.assert_not_awaited()
        mock_session.rollback.assert_awaited()

    def test_storage_projection_keeps_row_metadata_distinct(self):
        row = MagicMock()
        row.id = uuid4()
        row.workflow_id = "test_workflow_001"
        row.execution_id = "test_execution_001"
        row.organization_id = uuid4()
        row.created_at = datetime.now(UTC)
        row.event_type = EventType.WORKFLOW_EXECUTION_STARTED.value
        row.event = {
            "event_id": str(uuid4()),
            "created_at": "2020-01-01T00:00:00Z",
        }

        result = EventRepository._to_dto(row)

        assert result.id == row.id
        assert result.created_at == row.created_at
        assert result.event["event_id"] != str(result.id)
        assert result.event["created_at"] != result.created_at.isoformat()

    async def test_get_events_by_execution_id(self, event_repository, mock_session):
        """Test retrieving events by execution ID."""
        # Arrange
        mock_events = [
            EventDTO(
                id=uuid4(),
                created_at=datetime.now(UTC),
                organization_id=uuid4(),
                workflow_id="test_workflow_001",
                execution_id="test_execution_001",
                event_type=EventType.WORKFLOW_EXECUTION_STARTED,
                event={
                    "test": "data1",
                    "classification_parameters": {},
                    "extraction_parameters": {},
                },
            ),
            EventDTO(
                id=uuid4(),
                created_at=datetime.now(UTC),
                organization_id=uuid4(),
                workflow_id="test_workflow_001",
                execution_id="test_execution_001",
                event_type=EventType.WORKFLOW_EXECUTION_COMPLETED,
                event={"test": "data2"},
            ),
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_events
        mock_session.execute.return_value = mock_result

        # Act
        result = await event_repository.get_events_by_execution_id(
            execution_id="test_execution_001"
        )

        # Assert
        assert len(result) == 2
        assert all(isinstance(event, EventDTO) for event in result)
        assert result[0].execution_id == "test_execution_001"
        assert result[1].execution_id == "test_execution_001"

    async def test_get_events_by_execution_id_with_workflow_filter(
        self, event_repository, mock_session
    ):
        """Test retrieving events by execution ID with workflow filter."""
        # Arrange
        mock_events = [
            EventDTO(
                id=uuid4(),
                workflow_id="test_workflow_001",
                organization_id=uuid4(),
                execution_id="test_execution_001",
                created_at=datetime.now(UTC),
                event_type=EventType.WORKFLOW_EXECUTION_STARTED,
                event={"test": "data"},
            )
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_events
        mock_session.execute.return_value = mock_result

        # Act
        result = await event_repository.get_events_by_execution_id(
            execution_id="test_execution_001", workflow_id="test_workflow_001"
        )

        # Assert
        assert len(result) == 1
        assert result[0].workflow_id == "test_workflow_001"

    async def test_get_events_by_execution_id_with_limit_and_offset(
        self, event_repository, mock_session
    ):
        """Test retrieving events with limit and offset."""
        # Arrange
        mock_events = [
            EventDTO(
                id=uuid4(),
                workflow_id="test_workflow_001",
                organization_id=uuid4(),
                execution_id="test_execution_001",
                created_at=datetime.now(UTC),
                event_type=EventType.WORKFLOW_EXECUTION_STARTED,
                event={"test": "data"},
            )
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_events
        mock_session.execute.return_value = mock_result

        # Act
        result = await event_repository.get_events_by_execution_id(
            execution_id="test_execution_001", limit=10, offset=5
        )

        # Assert
        assert len(result) == 1
        mock_session.execute.assert_called_once()

    async def test_get_last_event_by_execution_id_found(
        self, event_repository, mock_session
    ):
        """Test retrieving last (latest) event for an execution id."""
        # Arrange: mock scalars().first() chain
        dummy_event = MagicMock()
        dummy_event.id = uuid4()
        dummy_event.workflow_id = "wf123"
        dummy_event.execution_id = "exec123"
        dummy_event.created_at = datetime.now(UTC)
        dummy_event.event_type = EventType.WORKFLOW_EXECUTION_COMPLETED.value
        dummy_event.event = {"status": "ok"}
        dummy_event.version = 5

        mock_scalars = MagicMock()
        mock_scalars.first.return_value = dummy_event
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        # Act
        result = await event_repository.get_last_event_by_execution_id(
            execution_id="exec123"
        )

        # Assert
        assert result is not None
        assert result.execution_id == "exec123"
        assert result.event_type == EventType.WORKFLOW_EXECUTION_COMPLETED
        assert result.event == {"status": "ok"}

    async def test_get_last_event_by_execution_id_not_found(
        self, event_repository, mock_session
    ):
        """Test retrieving last event returns None when no event exists."""
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = None
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await event_repository.get_last_event_by_execution_id(
            execution_id="unknown"
        )
        assert result is None


class TestGetCreatedEventIfExecutionNotCompletedOrFailed:
    def _make_entity(
        self, *, evt_type, created_at, wf_id="wf1", exec_id="exec1", payload=None
    ):
        row = MagicMock()
        row.id = uuid4()
        row.workflow_id = wf_id
        row.execution_id = exec_id
        row.created_at = created_at
        row.event_type = evt_type
        row.event = payload or {}
        return row

    async def test_returns_none_when_latest_event_is_completed(
        self, event_repository, mock_session
    ):
        now = datetime.now(UTC)
        newest = self._make_entity(
            evt_type=EventType.WORKFLOW_EXECUTION_COMPLETED, created_at=now
        )
        oldest = self._make_entity(
            evt_type=EventType.WORKFLOW_EXECUTION_STARTED,
            created_at=now.replace(year=now.year - 1),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [newest, oldest]
        mock_session.execute.return_value = mock_result

        result = await event_repository.get_created_event_if_execution_not_completed_or_failed(
            "exec1"
        )
        assert result is None

    async def test_returns_started_when_latest_event_is_started(
        self, event_repository, mock_session
    ):
        now = datetime.now(UTC)
        newest = self._make_entity(
            evt_type=EventType.WORKFLOW_EXECUTION_STARTED, created_at=now
        )
        oldest_failed = self._make_entity(
            evt_type=EventType.WORKFLOW_EXECUTION_FAILED,
            created_at=now.replace(year=now.year - 1),
            payload={"error_type": "Other"},
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [newest, oldest_failed]
        mock_session.execute.return_value = mock_result

        result = await event_repository.get_created_event_if_execution_not_completed_or_failed(
            "exec1"
        )
        assert isinstance(result, EventDTO)
        assert result.event_type == EventType.WORKFLOW_EXECUTION_STARTED
        assert result.execution_id == "exec1"

    async def test_retryable_failed_picks_started_event(
        self, event_repository, mock_session
    ):
        now = datetime.now(UTC)
        # The latest failure is retryable, so resume from its preceding start.
        newest_failed = self._make_entity(
            evt_type=EventType.WORKFLOW_EXECUTION_FAILED,
            created_at=now,
            payload={"error_type": RetryableException.__name__},
        )
        prior_started = self._make_entity(
            evt_type=EventType.WORKFLOW_EXECUTION_STARTED,
            created_at=now.replace(year=now.year - 1),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            newest_failed,
            prior_started,
        ]
        mock_session.execute.return_value = mock_result

        result = await event_repository.get_created_event_if_execution_not_completed_or_failed(
            "exec1"
        )
        assert isinstance(result, EventDTO)
        assert result.event_type == EventType.WORKFLOW_EXECUTION_STARTED

    async def test_non_retryable_failed_returns_none(
        self, event_repository, mock_session
    ):
        now = datetime.now(UTC)
        newest = self._make_entity(
            evt_type=EventType.WORKFLOW_EXECUTION_FAILED,
            created_at=now,
            payload={"error_type": "SomeOther"},
        )
        oldest_started = self._make_entity(
            evt_type=EventType.WORKFLOW_EXECUTION_STARTED,
            created_at=now.replace(year=now.year - 1),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [newest, oldest_started]
        mock_session.execute.return_value = mock_result

        result = await event_repository.get_created_event_if_execution_not_completed_or_failed(
            "exec1"
        )
        assert result is None

    async def test_latest_progress_event_prevents_reexecution(
        self, event_repository, mock_session
    ):
        now = datetime.now(UTC)
        newest = self._make_entity(
            evt_type=EventType.WORKFLOW_EXECUTION_STEP_COMPLETED, created_at=now
        )
        oldest_started = self._make_entity(
            evt_type=EventType.WORKFLOW_EXECUTION_STARTED,
            created_at=now.replace(year=now.year - 1),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [newest, oldest_started]
        mock_session.execute.return_value = mock_result

        result = await event_repository.get_created_event_if_execution_not_completed_or_failed(
            "exec1"
        )
        assert result is None

    async def test_retryable_failure_without_start_event_returns_none(
        self, event_repository, mock_session
    ):
        failed = self._make_entity(
            evt_type=EventType.WORKFLOW_EXECUTION_FAILED,
            created_at=datetime.now(UTC),
            payload={"error_type": RetryableException.__name__},
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [failed]
        mock_session.execute.return_value = mock_result

        result = await event_repository.get_created_event_if_execution_not_completed_or_failed(
            "exec1"
        )
        assert result is None

    async def test_oserror_raises_retryable_exception(
        self, event_repository, mock_session
    ):
        mock_session.execute.side_effect = OSError("db connection down")
        with pytest.raises(RetryableException):
            await (
                event_repository.get_created_event_if_execution_not_completed_or_failed(
                    "exec1"
                )
            )

    async def test_empty_events_list_returns_none(self, event_repository, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await event_repository.get_created_event_if_execution_not_completed_or_failed(
            "exec1"
        )
        assert result is None
        mock_session.rollback.assert_not_called()

    def test_anonymize_payload_started(self):
        payload = {
            "s3_file_info": {"filename": "test.pdf", "presigned_url": "https://secret"},
            "file_info": {"legacy": "data"},
            "file_url": "https://secret/test.pdf",
            "metadata": {"user": "alice", "ip": "1.2.3.4"},
            "workflow_id": "wf-1",
        }
        res = EventRepository.anonymize_payload("WorkflowExecutionStarted", payload)
        assert res["s3_file_info"] is None
        assert "file_info" not in res
        assert res["file_url"] is None
        assert res["metadata"] == {}
        assert res["workflow_id"] == "wf-1"

        # Also verify with EventType enum
        payload_enum = {
            "s3_file_info": {"filename": "test.pdf"},
            "file_info": {"legacy": "data"},
            "file_url": "https://secret",
            "metadata": {},
        }
        res_enum = EventRepository.anonymize_payload(
            EventType.WORKFLOW_EXECUTION_STARTED, payload_enum
        )
        assert res_enum["s3_file_info"] is None
        assert "file_info" not in res_enum
        assert res_enum["file_url"] is None

    def test_anonymize_payload_step_completed(self):
        payload = {
            "step_name": "ocr_step",
            "step_result": {"text": "Confidential extracted OCR text"},
            "execution_time_ms": 250,
            "output_data": {"extracted_data": "sensitive"},
        }
        res = EventRepository.anonymize_payload(
            "WorkflowExecutionStepCompleted", payload
        )
        assert res["step_result"] == {}
        assert res["output_data"] is None
        assert res["step_name"] == "ocr_step"
        assert res["execution_time_ms"] == 250

    def test_anonymize_payload_completed(self):
        payload = {
            "final_result": {
                "classification": {"type": "CNI"},
                "extraction": {"name": "Jean Dupont"},
            },
            "output_summary": {"summary": "sensitive summary"},
            "workflow_metadata": [{"info": "sensitive context"}],
            "total_processing_time_ms": 1200,
            "steps_completed": 4,
        }
        res = EventRepository.anonymize_payload("WorkflowExecutionCompleted", payload)
        assert res["final_result"] == {}
        assert res["output_summary"] == {}
        assert res["workflow_metadata"] is None
        assert res["total_processing_time_ms"] == 1200
        assert res["steps_completed"] == 4

    def test_anonymize_payload_failed(self):
        payload = {
            "error_type": "ValueError",
            "error_message": "Document contains invalid token secret_token_12345",
            "failed_step": "extraction",
            "retry_count": 2,
        }
        res = EventRepository.anonymize_payload("WorkflowExecutionFailed", payload)
        assert res["error_message"] == "[PURGED]"
        assert res["error_type"] == "ValueError"
        assert res["failed_step"] == "extraction"
        assert res["retry_count"] == 2

    def test_to_dto_anonymization_status(self):
        entity = EventEntity(
            id=uuid4(),
            workflow_id="wf_1",
            execution_id="exec_1",
            organization_id=uuid4(),
            created_at=datetime.now(UTC),
            event_type="WorkflowExecutionCompleted",
            event={"final_result": {}},
            anonymization_status="DONE",
        )
        dto = EventRepository._to_dto(entity)
        assert dto.anonymization_status == AnonymizationStatus.DONE

        entity.anonymization_status = "ERROR"
        dto_err = EventRepository._to_dto(entity)
        assert dto_err.anonymization_status == AnonymizationStatus.ERROR

    async def test_get_events_to_anonymize(self, event_repository, mock_session):
        cutoff = datetime.now(timezone.utc)
        entity1 = EventEntity(
            id=uuid4(),
            workflow_id="wf_1",
            execution_id="exec_1",
            organization_id=uuid4(),
            created_at=cutoff - timedelta(days=31),
            event_type="WorkflowExecutionCompleted",
            event={},
            anonymization_status="PENDING",
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [entity1]
        mock_session.execute.return_value = mock_result

        events = await event_repository.get_events_to_anonymize(
            before_date=cutoff,
            statuses=["PENDING", "ERROR"],
            limit=500,
        )
        assert len(events) == 1
        assert events[0].id == entity1.id
        mock_session.execute.assert_called_once()
        mock_session.expunge_all.assert_called_once()

    async def test_get_oldest_pending_event_age_seconds_none_when_empty(
        self, event_repository, mock_session
    ):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        age = await event_repository.get_oldest_pending_event_age_seconds()
        assert age is None

    async def test_get_oldest_pending_event_age_seconds_calculates_diff(
        self, event_repository, mock_session
    ):
        ten_minutes_ago = datetime.now(timezone.utc) - timedelta(seconds=600)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ten_minutes_ago
        mock_session.execute.return_value = mock_result

        age = await event_repository.get_oldest_pending_event_age_seconds()
        assert age is not None
        assert 595.0 <= age <= 605.0

    async def test_bulk_insert_events_uses_upsert(self, event_repository, mock_session):
        entity = EventEntity(
            id=uuid4(),
            workflow_id="wf_1",
            execution_id="exec_1",
            organization_id=uuid4(),
            created_at=datetime.now(timezone.utc),
            event_type="WorkflowExecutionStarted",
            event={"file_url": None},
            anonymization_status="DONE",
        )
        await event_repository.bulk_insert_events([entity])
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
        stmt = mock_session.execute.call_args[0][0]
        # Verify the statement compiles to an ON CONFLICT DO UPDATE
        stmt_str = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "ON CONFLICT" in stmt_str
        assert "DO UPDATE" in stmt_str
        assert "anonymization_status" in stmt_str

    async def test_anonymize_event_rollback_on_failure(
        self, event_repository, mock_session
    ):
        entity = EventEntity(
            id=uuid4(),
            workflow_id="wf_1",
            execution_id="exec_1",
            organization_id=uuid4(),
            created_at=datetime.now(timezone.utc),
            event_type="WorkflowExecutionCompleted",
            event={"final_result": {}},
            anonymization_status="PENDING",
        )
        mock_session.commit.side_effect = RuntimeError("DB commit failed")

        with pytest.raises(RuntimeError, match="DB commit failed"):
            await event_repository.anonymize_event(entity)

        mock_session.rollback.assert_awaited_once()

    async def test_save_failed_anonymization_rollback_on_failure(
        self, event_repository, mock_session
    ):
        entity = EventEntity(
            id=uuid4(),
            workflow_id="wf_1",
            execution_id="exec_1",
            organization_id=uuid4(),
            created_at=datetime.now(timezone.utc),
            event_type="WorkflowExecutionCompleted",
            event={},
            anonymization_status="PENDING",
        )
        mock_session.commit.side_effect = RuntimeError("DB commit failed")

        with pytest.raises(RuntimeError, match="DB commit failed"):
            await event_repository.save_failed_anonymization(entity)

        mock_session.rollback.assert_awaited_once()

    async def test_save_failed_anonymization_accepts_uuid(
        self, event_repository, mock_session
    ):
        target_id = uuid4()
        await event_repository.save_failed_anonymization(target_id)
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_awaited_once()

    def test_anonymize_payload_unknown_event_type_raises_value_error(self):
        payload = {"data": "preserved"}
        with pytest.raises(
            ValueError,
            match="Unsupported event_type for anonymization: 'UnknownEventType'",
        ):
            EventRepository.anonymize_payload("UnknownEventType", payload)

    async def test_count_events_by_statuses(self, event_repository, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 42
        mock_session.execute.return_value = mock_result

        count = await event_repository.count_events_by_statuses(["DONE", "ERROR"])
        assert count == 42
        mock_session.execute.assert_called_once()

    async def test_get_events_by_cursor(self, event_repository, mock_session):
        entity = EventEntity(
            id=uuid4(),
            workflow_id="wf_1",
            execution_id="exec_1",
            organization_id=uuid4(),
            created_at=datetime.now(timezone.utc),
            event_type="WorkflowExecutionCompleted",
            event={},
            anonymization_status="DONE",
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [entity]
        mock_session.execute.return_value = mock_result

        events = await event_repository.get_events_by_cursor(
            statuses=["DONE", "ERROR"],
            limit=50,
            after_id=uuid4(),
        )
        assert len(events) == 1
        assert events[0].id == entity.id
