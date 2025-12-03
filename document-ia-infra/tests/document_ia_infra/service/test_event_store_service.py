"""
Unit tests for EventStoreService.

This module contains comprehensive unit tests for the event store service,
testing business logic and event orchestration functionality.
"""

from datetime import datetime, UTC
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_infra.data.event.schema.event import EventStoreRecord
from document_ia_infra.data.event.schema.workflow.workflow_execution_completed_event import CompletedEventResult, \
    WorkflowExecutionCompletedEvent
from document_ia_infra.data.event.schema.workflow.workflow_execution_failed_event import WorkflowExecutionFailedEvent
from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import WorkflowExecutionStartedEvent, \
    ClassificationParameters, ExtractionParameters
from document_ia_infra.data.event.schema.workflow.workflow_execution_step_completed_event import \
    WorkflowExecutionStepCompletedEvent
from document_ia_infra.service.event_store_service import EventStoreService


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


def _sample_file_info():
    return FileInfo(
        filename="test.pdf",
        size=1024,
        content_type="application/pdf",
        s3_key="uploads/test.pdf",
        uploaded_at=datetime.now(UTC).isoformat(),
        presigned_url="https://example.com/presigned_url",
    )


@pytest.fixture
def sample_event():
    """Sample event for testing."""
    return WorkflowExecutionStartedEvent(
        event_id=uuid4(),
        organization_id=uuid4(),
        workflow_id="test_workflow_001",
        execution_id="test_execution_001",
        created_at=datetime.now(UTC),
        version=1,
        s3_file_info=_sample_file_info(),
        metadata={"source": "test"},
        classification_parameters=ClassificationParameters(),
        extraction_parameters=ExtractionParameters(),
    )


@pytest.fixture
def sample_event_record():
    """Sample event record for testing."""
    return EventDTO(
        id=uuid4(),
        workflow_id="test_workflow_001",
        organization_id=uuid4(),
        execution_id="test_execution_001",
        created_at=datetime.now(UTC),
        event_type=EventType.WORKFLOW_EXECUTION_STARTED,
        event={
            "event_id": str(uuid4()),
            "organization_id": str(uuid4()),
            "workflow_id": "test_workflow_001",
            "execution_id": "test_execution_001",
            "created_at": datetime.now(UTC).isoformat(),
            "version": 1,
            "event_type": "WorkflowExecutionStarted",
            "file_info": _sample_file_info(),
            "metadata": {"source": "test"},
            "classification_parameters": {},
            "extraction_parameters": {},
        },
    )


class TestEventStoreService:
    """Test cases for EventStoreService."""

    async def test_store_event_success(
            self, event_store_service, mock_repository, sample_event
    ):
        """Test successful event storage."""
        # Arrange
        mock_stored_event = EventDTO(
            id=uuid4(),
            organization_id=uuid4(),
            workflow_id="test_workflow_001",
            execution_id="test_execution_001",
            created_at=datetime.now(UTC),
            event_type=EventType.WORKFLOW_EXECUTION_STARTED,
            event=sample_event.model_dump(mode="python"),
        )

        mock_repository.put_event.return_value = mock_stored_event

        # Act
        result = await event_store_service.store_event(sample_event)

        # Assert
        assert isinstance(result, EventStoreRecord)
        assert result.workflow_id == "test_workflow_001"
        assert result.execution_id == "test_execution_001"
        mock_repository.put_event.assert_called_once()

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
            organization_id=uuid4(),
            execution_id="test_execution_001",
            file_info=_sample_file_info(),
            metadata={"source": "test"},
        )

        # Assert
        assert isinstance(event, WorkflowExecutionStartedEvent)
        assert event.workflow_id == "test_workflow_001"
        assert event.execution_id == "test_execution_001"
        assert event.s3_file_info.filename == "test.pdf"
        assert event.metadata == {"source": "test"}

    def test_create_step_completed_event(self, event_store_service):
        """Test creating step completed event."""
        # Act
        event = event_store_service.create_step_completed_event(
            workflow_id="test_workflow_001",
            organization_id=uuid4(),
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
            organization_id=uuid4(),
            execution_id="test_execution_001",
            final_result=CompletedEventResult(),
            total_processing_time_ms=5000,
            output_summary={"steps": 3, "success": True},
            steps_completed=3,
        )

        # Assert
        assert isinstance(event, WorkflowExecutionCompletedEvent)
        assert event.workflow_id == "test_workflow_001"
        assert event.execution_id == "test_execution_001"
        assert event.final_result is not None
        assert event.total_processing_time_ms == 5000
        assert event.output_summary == {"steps": 3, "success": True}
        assert event.steps_completed == 3

    def test_create_workflow_failed_event(self, event_store_service):
        """Test creating workflow failed event."""
        # Act
        event = event_store_service.create_workflow_failed_event(
            workflow_id="test_workflow_001",
            organization_id=uuid4(),
            execution_id="test_execution_001",
            error_type="ProcessingError",
            error_message="Failed to process document",
            failed_step="preprocessing",
            retry_count=2,
        )

        # Assert
        assert isinstance(event, WorkflowExecutionFailedEvent)
        assert event.workflow_id == "test_workflow_001"
        assert event.execution_id == "test_execution_001"
        assert event.error_type == "ProcessingError"
        assert event.error_message == "Failed to process document"
        assert event.failed_step == "preprocessing"
        assert event.retry_count == 2

    # High-level workflow event orchestration method tests

    async def test_emit_workflow_started(
            self, event_store_service, mock_repository, sample_event_record
    ):
        """Test emitting workflow started event."""
        # Arrange
        mock_repository.put_event.return_value = sample_event_record

        # Act
        result = await event_store_service.emit_workflow_started(
            workflow_id="test_workflow_001",
            organization_id=uuid4(),
            execution_id="test_execution_001",
            file_info=_sample_file_info(),
            metadata={"source": "test"},
        )

        # Assert
        assert isinstance(result, EventStoreRecord)
        mock_repository.put_event.assert_called_once()

    async def test_emit_step_completed(
            self, event_store_service, mock_repository, sample_event_record
    ):
        """Test emitting step completed event."""
        # Arrange
        mock_repository.put_event.return_value = sample_event_record

        # Act
        result = await event_store_service.emit_step_completed(
            workflow_id="test_workflow_001",
            organization_id=uuid4(),
            execution_id="test_execution_001",
            step_name="preprocessing",
            step_result={"status": "success"},
            execution_time_ms=1500,
            output_data={"processed": True},
        )

        # Assert
        assert isinstance(result, EventStoreRecord)
        mock_repository.put_event.assert_called_once()

    async def test_emit_workflow_completed(
            self, event_store_service, mock_repository, sample_event_record
    ):
        """Test emitting workflow completed event."""
        # Arrange
        mock_repository.put_event.return_value = sample_event_record

        # Act
        result = await event_store_service.emit_workflow_completed(
            workflow_id="test_workflow_001",
            organization_id=uuid4(),
            execution_id="test_execution_001",
            final_result={"status": "completed"},
            total_processing_time_ms=5000,
            output_summary={"steps": 3, "success": True},
            steps_completed=3,
        )

        # Assert
        assert isinstance(result, EventStoreRecord)
        mock_repository.put_event.assert_called_once()

    async def test_emit_workflow_failed(
            self, event_store_service, mock_repository, sample_event_record
    ):
        """Test emitting workflow failed event."""
        # Arrange
        mock_repository.put_event.return_value = sample_event_record

        # Act
        result = await event_store_service.emit_workflow_failed(
            workflow_id="test_workflow_001",
            organization_id=uuid4(),
            execution_id="test_execution_001",
            error_type="ProcessingError",
            error_message="Failed to process document",
            failed_step="preprocessing",
            retry_count=2,
        )

        # Assert
        assert isinstance(result, EventStoreRecord)
        mock_repository.put_event.assert_called_once()
