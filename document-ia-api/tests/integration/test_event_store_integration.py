"""
Integration tests for event store functionality.

This module contains integration tests that test the complete event store
functionality with real database interactions.
"""

import pytest
from uuid import uuid4
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from infra.database.database import build_database_uri
from application.services.event_store_service import EventStoreService
from schemas.events import EventStoreRecord, EventStream


@pytest.fixture(scope="function")
async def db_session():
    """Create a real database session for integration tests."""
    # Create a fresh engine for each test to avoid connection sharing issues
    engine = create_async_engine(build_database_uri(), echo=False, future=True)
    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()

    # Clean up the engine
    await engine.dispose()


@pytest.fixture(scope="function")
async def event_store_service(db_session):
    """Create an EventStoreService with real database session."""
    return EventStoreService(db_session)


@pytest.mark.asyncio
class TestEventStoreIntegration:
    """Integration tests for event store functionality."""

    async def test_full_event_lifecycle(self, event_store_service, db_session):
        """Test complete event lifecycle from creation to retrieval."""
        # Arrange
        workflow_id = "integration_test_workflow"
        execution_id = str(uuid4())

        # Act - Store workflow started event
        started_event = await event_store_service.emit_workflow_started(
            workflow_id=workflow_id,
            execution_id=execution_id,
            file_info={"filename": "integration_test.pdf", "size": 2048},
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

        # Assert - Verify event versions are sequential
        assert started_event.version == 1
        assert step_event.version == 2
        assert completed_event.version == 3

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
        started_data = events[0].event
        assert started_data["file_info"]["filename"] == "integration_test.pdf"
        assert started_data["metadata"]["source"] == "integration_test"

        step_data = events[1].event
        assert step_data["step_name"] == "preprocessing"
        assert step_data["execution_time_ms"] == 1500

        completed_data = events[2].event
        assert completed_data["final_result"]["status"] == "completed"
        assert completed_data["steps_completed"] == 3

    async def test_event_version_consistency(self, event_store_service, db_session):
        """Test that event versions are consistent and sequential."""
        # Arrange
        workflow_id = "version_test_workflow"
        execution_id = str(uuid4())

        # Act - Create multiple events for the same execution
        events = []
        for i in range(5):
            if i == 0:
                event = await event_store_service.emit_workflow_started(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    file_info={"filename": f"version_test_{i}.pdf"},
                    metadata={"step": i},
                )
            elif i == 4:
                event = await event_store_service.emit_workflow_completed(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    final_result={"status": "completed"},
                    total_processing_time_ms=1000 * i,
                    output_summary={"steps": i},
                    steps_completed=i,
                )
            else:
                event = await event_store_service.emit_step_completed(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    step_name=f"step_{i}",
                    step_result={"step": i},
                    execution_time_ms=1000 * i,
                )
            events.append(event)

        # Assert - Verify versions are sequential
        for i, event in enumerate(events):
            assert event.version == i + 1, (
                f"Event {i} has incorrect version: {event.version}"
            )

        # Assert - Verify event stream has correct versions
        event_stream = await event_store_service.get_event_stream(
            execution_id=execution_id
        )

        for i, event in enumerate(event_stream.events):
            assert event.version == i + 1, (
                f"Stream event {i} has incorrect version: {event.version}"
            )
