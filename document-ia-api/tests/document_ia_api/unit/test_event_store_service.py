"""
Unit tests for EventStoreService.

This module contains comprehensive unit tests for the event store service,
testing business logic and event orchestration functionality.
"""

import pytest
from unittest.mock import AsyncMock
from datetime import datetime, UTC
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.application.services.event_store_service import EventStoreService
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_api.schemas.events import (
    EventStoreRecord,
    WorkflowExecutionStartedEvent,
    WorkflowExecutionStepCompletedEvent,
    WorkflowExecutionCompletedEvent,
    WorkflowExecutionFailedEvent,
)


@pytest.fixture
def mock_session():
    """Create a mock async database session."""
    session = AsyncMock(spec=AsyncSession)
    return session


@pytest.fixture
def mock_repository():
    """Create a mock event store repository."""
    repository = AsyncMock(spec=EventRepository)
    return repository


@pytest.fixture
def event_store_service(mock_session, mock_repository):
    """Create an EventStoreService instance with mock dependencies."""
    service = EventStoreService(mock_session)
    service.repository = mock_repository
    return service


@pytest.fixture
def sample_event():
    """Sample event for testing."""
    return WorkflowExecutionStartedEvent(
        event_id=uuid4(),
        workflow_id="test_workflow_001",
        execution_id="test_execution_001",
        created_at=datetime.now(UTC),
        version=1,
        file_info={"filename": "test.pdf", "size": 1024},
        metadata={"source": "test"},
    )


@pytest.fixture
def sample_event_record():
    """Sample event record for testing."""
    return EventStoreRecord(
        id=uuid4(),
        workflow_id="test_workflow_001",
        execution_id="test_execution_001",
        created_at=datetime.now(UTC),
        event_type=EventType.WORKFLOW_EXECUTION_STARTED,
        event={
            "event_id": str(uuid4()),
            "workflow_id": "test_workflow_001",
            "execution_id": "test_execution_001",
            "created_at": datetime.now(UTC).isoformat(),
            "version": 1,
            "event_type": "WorkflowExecutionStarted",
            "file_info": {"filename": "test.pdf"},
            "metadata": {"source": "test"},
        },
        version=1,
    )


class TestEventStoreService:
    """Test cases for EventStoreService."""

    async def test_store_event_success(
        self, event_store_service, mock_repository, sample_event
    ):
        """Test successful event storage."""
        # Arrange
        mock_stored_event = EventStoreRecord(
            id=uuid4(),
            workflow_id="test_workflow_001",
            execution_id="test_execution_001",
            created_at=datetime.now(UTC),
            event_type=EventType.WORKFLOW_EXECUTION_STARTED,
            event=sample_event.model_dump(),
            version=2,
        )

        mock_repository.get_latest_event_version.return_value = 1
        mock_repository.put_event.return_value = mock_stored_event

        # Act
        result = await event_store_service.store_event(sample_event)

        # Assert
        assert isinstance(result, EventStoreRecord)
        assert result.workflow_id == "test_workflow_001"
        assert result.execution_id == "test_execution_001"
        mock_repository.get_latest_event_version.assert_called_once_with(
            execution_id="test_execution_001", workflow_id="test_workflow_001"
        )
        mock_repository.put_event.assert_called_once()

    async def test_store_event_exception(
        self, event_store_service, mock_repository, sample_event
    ):
        """Test event storage with exception."""
        # Arrange
        mock_repository.get_latest_event_version.side_effect = Exception(
            "Database error"
        )

        # Act & Assert
        with pytest.raises(Exception, match="Database error"):
            await event_store_service.store_event(sample_event)

    async def test_get_events_by_execution_id(
        self, event_store_service, mock_repository, sample_event_record
    ):
        """Test getting events by execution ID."""
        # Arrange
        mock_repository.get_events_by_execution_id.return_value = [sample_event_record]

        # Act
        result = await event_store_service.get_events_by_execution_id(
            execution_id="test_execution_001"
        )

        # Assert
        assert len(result) == 1
        assert result[0].execution_id == "test_execution_001"
        mock_repository.get_events_by_execution_id.assert_called_once_with(
            execution_id="test_execution_001", workflow_id=None, limit=None, offset=0
        )

    # Event creation helper method tests

    def test_create_workflow_started_event(self, event_store_service):
        """Test creating workflow started event."""
        # Act
        event = event_store_service.create_workflow_started_event(
            workflow_id="test_workflow_001",
            execution_id="test_execution_001",
            file_info={"filename": "test.pdf"},
            metadata={"source": "test"},
        )

        # Assert
        assert isinstance(event, WorkflowExecutionStartedEvent)
        assert event.workflow_id == "test_workflow_001"
        assert event.execution_id == "test_execution_001"
        assert event.file_info == {"filename": "test.pdf"}
        assert event.metadata == {"source": "test"}

    def test_create_step_completed_event(self, event_store_service):
        """Test creating step completed event."""
        # Act
        event = event_store_service.create_step_completed_event(
            workflow_id="test_workflow_001",
            execution_id="test_execution_001",
            step_name="preprocessing",
            step_result={"status": "success"},
            execution_time_ms=1500,
            output_data={"processed": True},
        )

        # Assert
        assert isinstance(event, WorkflowExecutionStepCompletedEvent)
        assert event.workflow_id == "test_workflow_001"
        assert event.execution_id == "test_execution_001"
        assert event.step_name == "preprocessing"
        assert event.step_result == {"status": "success"}
        assert event.execution_time_ms == 1500
        assert event.output_data == {"processed": True}

    def test_create_workflow_completed_event(self, event_store_service):
        """Test creating workflow completed event."""
        # Act
        event = event_store_service.create_workflow_completed_event(
            workflow_id="test_workflow_001",
            execution_id="test_execution_001",
            final_result={"status": "completed"},
            total_processing_time_ms=5000,
            output_summary={"steps": 3, "success": True},
            steps_completed=3,
        )

        # Assert
        assert isinstance(event, WorkflowExecutionCompletedEvent)
        assert event.workflow_id == "test_workflow_001"
        assert event.execution_id == "test_execution_001"
        assert event.final_result == {"status": "completed"}
        assert event.total_processing_time_ms == 5000
        assert event.output_summary == {"steps": 3, "success": True}
        assert event.steps_completed == 3

    def test_create_workflow_failed_event(self, event_store_service):
        """Test creating workflow failed event."""
        # Act
        event = event_store_service.create_workflow_failed_event(
            workflow_id="test_workflow_001",
            execution_id="test_execution_001",
            error_type="ProcessingError",
            error_message="Failed to process document",
            failed_step="preprocessing",
            retry_count=2,
            stack_trace="Traceback...",
        )

        # Assert
        assert isinstance(event, WorkflowExecutionFailedEvent)
        assert event.workflow_id == "test_workflow_001"
        assert event.execution_id == "test_execution_001"
        assert event.error_type == "ProcessingError"
        assert event.error_message == "Failed to process document"
        assert event.failed_step == "preprocessing"
        assert event.retry_count == 2
        assert event.stack_trace == "Traceback..."

    # High-level workflow event orchestration method tests

    async def test_emit_workflow_started(
        self, event_store_service, mock_repository, sample_event_record
    ):
        """Test emitting workflow started event."""
        # Arrange
        mock_repository.get_latest_event_version.return_value = 0
        mock_repository.put_event.return_value = sample_event_record

        # Act
        result = await event_store_service.emit_workflow_started(
            workflow_id="test_workflow_001",
            execution_id="test_execution_001",
            file_info={"filename": "test.pdf"},
            metadata={"source": "test"},
        )

        # Assert
        assert isinstance(result, EventStoreRecord)
        mock_repository.get_latest_event_version.assert_called_once()
        mock_repository.put_event.assert_called_once()

    async def test_emit_step_completed(
        self, event_store_service, mock_repository, sample_event_record
    ):
        """Test emitting step completed event."""
        # Arrange
        mock_repository.get_latest_event_version.return_value = 1
        mock_repository.put_event.return_value = sample_event_record

        # Act
        result = await event_store_service.emit_step_completed(
            workflow_id="test_workflow_001",
            execution_id="test_execution_001",
            step_name="preprocessing",
            step_result={"status": "success"},
            execution_time_ms=1500,
            output_data={"processed": True},
        )

        # Assert
        assert isinstance(result, EventStoreRecord)
        mock_repository.get_latest_event_version.assert_called_once()
        mock_repository.put_event.assert_called_once()

    async def test_emit_workflow_completed(
        self, event_store_service, mock_repository, sample_event_record
    ):
        """Test emitting workflow completed event."""
        # Arrange
        mock_repository.get_latest_event_version.return_value = 2
        mock_repository.put_event.return_value = sample_event_record

        # Act
        result = await event_store_service.emit_workflow_completed(
            workflow_id="test_workflow_001",
            execution_id="test_execution_001",
            final_result={"status": "completed"},
            total_processing_time_ms=5000,
            output_summary={"steps": 3, "success": True},
            steps_completed=3,
        )

        # Assert
        assert isinstance(result, EventStoreRecord)
        mock_repository.get_latest_event_version.assert_called_once()
        mock_repository.put_event.assert_called_once()

    async def test_emit_workflow_failed(
        self, event_store_service, mock_repository, sample_event_record
    ):
        """Test emitting workflow failed event."""
        # Arrange
        mock_repository.get_latest_event_version.return_value = 2
        mock_repository.put_event.return_value = sample_event_record

        # Act
        result = await event_store_service.emit_workflow_failed(
            workflow_id="test_workflow_001",
            execution_id="test_execution_001",
            error_type="ProcessingError",
            error_message="Failed to process document",
            failed_step="preprocessing",
            retry_count=2,
            stack_trace="Traceback...",
        )

        # Assert
        assert isinstance(result, EventStoreRecord)
        mock_repository.get_latest_event_version.assert_called_once()
        mock_repository.put_event.assert_called_once()
