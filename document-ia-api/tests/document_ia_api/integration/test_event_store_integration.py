"""
Integration tests for event store functionality.

This module contains integration tests that test the complete event store
functionality with real database interactions.
"""

from datetime import datetime, UTC
from typing import cast
from uuid import uuid4

import pytest

from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.data.database import database_manager
from document_ia_infra.data.event.schema.event import EventStoreRecord, EventStream
from document_ia_infra.data.event.schema.workflow.workflow_execution_completed_event import \
    WorkflowExecutionCompletedEvent
from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import WorkflowExecutionStartedEvent
from document_ia_infra.data.event.schema.workflow.workflow_execution_step_completed_event import \
    WorkflowExecutionStepCompletedEvent
from document_ia_infra.service.event_store_service import EventStoreService


@pytest.fixture(scope="function")
async def db_session():
    # Empêche la réutilisation d'une connexion asyncpg liée à un autre event loop
    await database_manager.async_engine.dispose()
    async with database_manager.local_session() as session:  # type: AsyncSession
        try:
            yield session
        finally:
            if session.in_transaction():
                await session.rollback()
            await session.close()


def _sample_file_info():
    return FileInfo(
        filename="integration_test.pdf",
        size=1024,
        content_type="application/pdf",
        s3_key="uploads/test.pdf",
        uploaded_at=datetime.now(UTC).isoformat(),
        presigned_url="https://example.com/presigned_url",
    )


@pytest.fixture(scope="function")
async def event_store_service(db_session):
    """Create an EventStoreService with real database session."""
    return EventStoreService(db_session)


class TestEventStoreIntegration:
    """Integration tests for event store functionality."""

    async def test_full_event_lifecycle(self, event_store_service, db_session):
        # Arrange
        workflow_id = "integration_test_workflow"
        execution_id = str(uuid4())

        # Act - Store workflow started event
        started_event = await event_store_service.emit_workflow_started(
            workflow_id=workflow_id,
            execution_id=execution_id,
            file_info=_sample_file_info(),
            metadata={"source": "integration_test", "priority": "high"},
        )

        # Act - Store step completed event
        step_event = await event_store_service.emit_step_completed(
            workflow_id=workflow_id,
            execution_id=execution_id,
            step_name="preprocessing",
            step_result={"status": "success", "confidence": 0.95},
            execution_time_ms=1500,
            output_data={"processed_pages": 5, "quality_score": 0.92},
        )

        # Act - Store workflow completed event
        completed_event = await event_store_service.emit_workflow_completed(
            workflow_id=workflow_id,
            execution_id=execution_id,
            final_result={"status": "completed", "total_pages": 5},
            total_processing_time_ms=5000,
            output_summary={"steps_completed": 3, "success_rate": 1.0},
            steps_completed=3,
        )

        # Assert - Verify all events were stored
        assert isinstance(started_event, EventStoreRecord)
        assert isinstance(step_event, EventStoreRecord)
        assert isinstance(completed_event, EventStoreRecord)

        # Act - Retrieve event stream
        event_stream = await event_store_service.get_event_stream(
            execution_id=execution_id
        )

        # Assert - Verify event stream
        assert isinstance(event_stream, EventStream)
        assert event_stream.execution_id == execution_id
        assert event_stream.workflow_id == workflow_id
        assert event_stream.total_events == 3
        assert len(event_stream.events) == 3
        assert event_stream.first_event_at is not None
        assert event_stream.last_event_at is not None

        # Assert - Verify event order and content
        events = event_stream.events
        assert events[0].event_type == "WorkflowExecutionStarted"
        assert events[1].event_type == "WorkflowExecutionStepCompleted"
        assert events[2].event_type == "WorkflowExecutionCompleted"

        # Assert - Verify event data integrity
        started_data: WorkflowExecutionStartedEvent = cast(WorkflowExecutionStartedEvent, events[0].event)
        assert started_data.file_info.filename == "integration_test.pdf"
        assert started_data.metadata["source"] == "integration_test"

        step_data: WorkflowExecutionStepCompletedEvent = cast(WorkflowExecutionStepCompletedEvent, events[1].event)
        assert step_data.step_name == "preprocessing"
        assert step_data.execution_time_ms == 1500

        completed_data: WorkflowExecutionCompletedEvent = cast(WorkflowExecutionCompletedEvent, events[2].event)
        assert completed_data.final_result is not None
        assert completed_data.steps_completed == 3
