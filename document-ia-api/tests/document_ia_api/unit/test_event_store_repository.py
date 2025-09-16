"""
Unit tests for EventStoreRepository.

This module contains comprehensive unit tests for the event store repository,
testing all CRUD operations and event stream functionality.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, UTC
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from document_ia_api.infra.database.repositories.event_store import EventStoreRepository
from document_ia_api.infra.database.models.event_store import EventStore
from document_ia_api.schemas.events import EventStoreRecord


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
def event_store_repository(mock_session):
    """Create an EventStoreRepository instance with mock session."""
    return EventStoreRepository(mock_session)


@pytest.fixture
def sample_event_data():
    """Sample event data for testing."""
    return {
        "event_id": str(uuid4()),
        "workflow_id": "test_workflow_001",
        "execution_id": "test_execution_001",
        "created_at": datetime.now().isoformat(),
        "version": 1,
        "event_type": "WorkflowExecutionStarted",
        "file_info": {"filename": "test.pdf", "size": 1024},
        "metadata": {"source": "test"},
    }


class TestEventStoreRepository:
    """Test cases for EventStoreRepository."""

    async def test_put_event_success(
        self, event_store_repository, mock_session, sample_event_data
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
        result = await event_store_repository.put_event(
            workflow_id="test_workflow_001",
            execution_id="test_execution_001",
            event_type="WorkflowExecutionStarted",
            event_data=sample_event_data,
            version=1,
        )

        # Assert
        assert isinstance(result, EventStoreRecord)
        assert result.workflow_id == "test_workflow_001"
        assert result.execution_id == "test_execution_001"
        assert result.event_type == "WorkflowExecutionStarted"
        assert result.version == 1
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()
        mock_session.refresh.assert_called_once()

    async def test_put_event_integrity_error(
        self, event_store_repository, mock_session, sample_event_data
    ):
        """Test event storage with integrity error."""
        # Arrange
        mock_session.flush.side_effect = IntegrityError("statement", "params", "orig")

        # Act & Assert
        with pytest.raises(IntegrityError):
            await event_store_repository.put_event(
                workflow_id="test_workflow_001",
                execution_id="test_execution_001",
                event_type="WorkflowExecutionStarted",
                event_data=sample_event_data,
                version=1,
            )

        mock_session.rollback.assert_called_once()

    async def test_get_events_by_execution_id(
        self, event_store_repository, mock_session
    ):
        """Test retrieving events by execution ID."""
        # Arrange
        mock_events = [
            EventStore(
                id=uuid4(),
                created_at=datetime.now(UTC),
                workflow_id="test_workflow_001",
                execution_id="test_execution_001",
                event_type="WorkflowExecutionStarted",
                event={"test": "data1"},
                version=1,
            ),
            EventStore(
                id=uuid4(),
                created_at=datetime.now(UTC),
                workflow_id="test_workflow_001",
                execution_id="test_execution_001",
                event_type="WorkflowExecutionCompleted",
                event={"test": "data2"},
                version=2,
            ),
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_events
        mock_session.execute.return_value = mock_result

        # Act
        result = await event_store_repository.get_events_by_execution_id(
            execution_id="test_execution_001"
        )

        # Assert
        assert len(result) == 2
        assert all(isinstance(event, EventStoreRecord) for event in result)
        assert result[0].execution_id == "test_execution_001"
        assert result[1].execution_id == "test_execution_001"

    async def test_get_events_by_execution_id_with_workflow_filter(
        self, event_store_repository, mock_session
    ):
        """Test retrieving events by execution ID with workflow filter."""
        # Arrange
        mock_events = [
            EventStore(
                id=uuid4(),
                workflow_id="test_workflow_001",
                execution_id="test_execution_001",
                created_at=datetime.now(UTC),
                event_type="WorkflowExecutionStarted",
                event={"test": "data"},
                version=1,
            )
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_events
        mock_session.execute.return_value = mock_result

        # Act
        result = await event_store_repository.get_events_by_execution_id(
            execution_id="test_execution_001", workflow_id="test_workflow_001"
        )

        # Assert
        assert len(result) == 1
        assert result[0].workflow_id == "test_workflow_001"

    async def test_get_events_by_execution_id_with_limit_and_offset(
        self, event_store_repository, mock_session
    ):
        """Test retrieving events with limit and offset."""
        # Arrange
        mock_events = [
            EventStore(
                id=uuid4(),
                workflow_id="test_workflow_001",
                execution_id="test_execution_001",
                created_at=datetime.now(UTC),
                event_type="WorkflowExecutionStarted",
                event={"test": "data"},
                version=1,
            )
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_events
        mock_session.execute.return_value = mock_result

        # Act
        result = await event_store_repository.get_events_by_execution_id(
            execution_id="test_execution_001", limit=10, offset=5
        )

        # Assert
        assert len(result) == 1
        mock_session.execute.assert_called_once()

    async def test_get_latest_event_version(self, event_store_repository, mock_session):
        """Test getting latest event version."""
        # Arrange
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_session.execute.return_value = mock_result

        # Act
        result = await event_store_repository.get_latest_event_version(
            execution_id="test_execution_001"
        )

        # Assert
        assert result == 5

    async def test_get_latest_event_version_no_events(
        self, event_store_repository, mock_session
    ):
        """Test getting latest event version when no events exist."""
        # Arrange
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        mock_session.execute.return_value = mock_result

        # Act
        result = await event_store_repository.get_latest_event_version(
            execution_id="nonexistent_execution"
        )

        # Assert
        assert result == 0
