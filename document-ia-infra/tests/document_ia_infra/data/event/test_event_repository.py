"""
Unit tests for EventStoreRepository.

This module contains comprehensive unit tests for the event store repository,
testing all CRUD operations and event stream functionality.
"""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_infra.exception.retryable_exception import RetryableException


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
                event={"test": "data1"},
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

    async def test_returns_none_when_last_event_is_completed(
        self, event_repository, mock_session
    ):
        now = datetime.now(UTC)
        # events list is ordered DESC by created_at according to query; code uses events[-1] (oldest)
        newest = self._make_entity(evt_type=EventType.WORKFLOW_EXECUTION_STARTED, created_at=now)
        oldest = self._make_entity(evt_type=EventType.WORKFLOW_EXECUTION_COMPLETED, created_at=now.replace(year=now.year-1))
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [newest, oldest]
        mock_session.execute.return_value = mock_result

        result = await event_repository.get_created_event_if_execution_not_completed_or_failed("exec1")
        assert result is None

    async def test_returns_started_when_last_event_is_started(
        self, event_repository, mock_session
    ):
        now = datetime.now(UTC)
        newest = self._make_entity(evt_type=EventType.WORKFLOW_EXECUTION_FAILED, created_at=now, payload={"error_type": "Other"})
        oldest_started = self._make_entity(evt_type=EventType.WORKFLOW_EXECUTION_STARTED, created_at=now.replace(year=now.year-1))
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [newest, oldest_started]
        mock_session.execute.return_value = mock_result

        result = await event_repository.get_created_event_if_execution_not_completed_or_failed("exec1")
        assert isinstance(result, EventDTO)
        assert result.event_type == EventType.WORKFLOW_EXECUTION_STARTED
        assert result.execution_id == "exec1"

    async def test_retryable_failed_picks_started_event(
        self, event_repository, mock_session
    ):
        now = datetime.now(UTC)
        # oldest is FAILED retryable, there is a STARTED more recent; code scans reversed(events) to find STARTED
        newest_started = self._make_entity(evt_type=EventType.WORKFLOW_EXECUTION_STARTED, created_at=now)
        oldest_failed = self._make_entity(evt_type=EventType.WORKFLOW_EXECUTION_FAILED, created_at=now.replace(year=now.year-1), payload={"error_type": RetryableException.__name__})
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [newest_started, oldest_failed]
        mock_session.execute.return_value = mock_result

        result = await event_repository.get_created_event_if_execution_not_completed_or_failed("exec1")
        assert isinstance(result, EventDTO)
        assert result.event_type == EventType.WORKFLOW_EXECUTION_STARTED

    async def test_non_retryable_failed_returns_none(
        self, event_repository, mock_session
    ):
        now = datetime.now(UTC)
        newest = self._make_entity(evt_type=EventType.WORKFLOW_EXECUTION_STARTED, created_at=now)
        oldest_failed = self._make_entity(evt_type=EventType.WORKFLOW_EXECUTION_FAILED, created_at=now.replace(year=now.year-1), payload={"error_type": "SomeOther"})
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [newest, oldest_failed]
        mock_session.execute.return_value = mock_result

        result = await event_repository.get_created_event_if_execution_not_completed_or_failed("exec1")
        assert result is None

    async def test_oserror_raises_retryable_exception(
        self, event_repository, mock_session
    ):
        mock_session.execute.side_effect = OSError("db connection down")
        with pytest.raises(RetryableException):
            await event_repository.get_created_event_if_execution_not_completed_or_failed("exec1")

    async def test_empty_events_list_raises_and_rolls_back(
        self, event_repository, mock_session
    ):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        with pytest.raises(Exception):
            await event_repository.get_created_event_if_execution_not_completed_or_failed("exec1")
        mock_session.rollback.assert_called_once()
