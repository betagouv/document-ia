"""
Event store service for business logic and event handling.

This module implements the application service layer for event store operations,
providing high-level business logic and event orchestration.
"""

import logging
from datetime import datetime, UTC
from typing import List, Optional, Dict, Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.api.exceptions.entity_not_found_exception import (
    EntityNotFoundException,
)
from document_ia_api.schemas.events import EventStoreRecord, EventStream
from document_ia_api.schemas.mappers.event_mapper import convert_event_dto
from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_infra.data.event.schema.event import (
    BaseEvent,
    WorkflowExecutionStartedEvent,
    WorkflowExecutionStepCompletedEvent,
    WorkflowExecutionCompletedEvent,
    WorkflowExecutionFailedEvent,
)

logger = logging.getLogger(__name__)


class EventStoreService:
    """Service for event store business logic and event handling."""

    def __init__(self, session: AsyncSession):
        self.repository = EventRepository(session)
        self.session = session

    async def get_last_event_for_execution_id(self, execution_id: str) -> EventDTO:
        try:
            event_dto = await self.repository.get_last_event_by_execution_id(
                execution_id
            )
            if not event_dto:
                raise EntityNotFoundException("event", execution_id)
            return event_dto

        except Exception as e:
            logger.error(
                f"Failed to get last event for execution_id {execution_id}: {e}"
            )
            raise

    async def store_event(self, event: BaseEvent) -> EventStoreRecord:
        """
        Store an event in the event store with automatic versioning.

        Args:
            event: The event to store

        Returns:
            EventStoreRecord: The stored event record

        Raises:
            ValueError: If event data is invalid
            Exception: If storage fails
        """
        try:
            # Get the next version for this execution
            next_version = (
                await self.repository.get_latest_event_version(
                    execution_id=event.execution_id, workflow_id=event.workflow_id
                )
                + 1
            )

            # Convert event to dictionary for storage with JSON serializable values
            event_data = event.model_dump(mode="json")

            # Store the event
            stored_event = await self.repository.put_event(
                workflow_id=event.workflow_id,
                execution_id=event.execution_id,
                event_type=event.event_type.value,
                event_data=event_data,
                version=next_version,
            )

            logger.info(
                f"Event stored successfully: {event.event_type} "
                f"for execution {event.execution_id} (version: {next_version})"
            )

            return convert_event_dto(stored_event)

        except Exception as e:
            logger.error(
                f"Failed to store event {event.event_type} "
                f"for execution {event.execution_id}: {e}"
            )
            raise

    async def get_events_by_execution_id(
        self,
        execution_id: str,
        workflow_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[EventStoreRecord]:
        """
        Retrieve events for a specific execution ID.

        Args:
            execution_id: Execution instance identifier
            workflow_id: Optional workflow identifier for additional filtering
            limit: Maximum number of events to return
            offset: Number of events to skip

        Returns:
            List[EventStoreRecord]: List of events ordered by creation time
        """
        event_dto_list = await self.repository.get_events_by_execution_id(
            execution_id=execution_id,
            workflow_id=workflow_id,
            limit=limit,
            offset=offset,
        )
        return [convert_event_dto(event_dto) for event_dto in event_dto_list]

    async def get_event_stream(
        self, execution_id: str, workflow_id: Optional[str] = None
    ) -> EventStream:
        """
        Retrieve complete event stream for an execution.

        Args:
            execution_id: Execution instance identifier
            workflow_id: Optional workflow identifier for additional filtering

        Returns:
            EventStream: Complete event stream with metadata
        """

        events = await self.get_events_by_execution_id(
            execution_id=execution_id, workflow_id=workflow_id
        )

        if not events:
            return EventStream(
                execution_id=execution_id,
                workflow_id=workflow_id or "",
                events=[],
                total_events=0,
                first_event_at=None,
                last_event_at=None,
            )

        return EventStream(
            execution_id=execution_id,
            workflow_id=workflow_id or events[0].workflow_id,
            events=events,
            total_events=len(events),
            first_event_at=events[0].created_at,
            last_event_at=events[-1].created_at,
        )

    # Event creation helper methods

    def create_workflow_started_event(
        self,
        workflow_id: str,
        execution_id: str,
        file_info: FileInfo,
        metadata: Dict[str, Any],
    ) -> WorkflowExecutionStartedEvent:
        """Create a WorkflowExecutionStartedEvent."""
        return WorkflowExecutionStartedEvent(
            workflow_id=workflow_id,
            execution_id=execution_id,
            created_at=datetime.now(),
            version=1,  # Will be updated when stored
            file_info=file_info,
            metadata=metadata,
        )

    def create_step_completed_event(
        self,
        workflow_id: str,
        execution_id: str,
        step_name: str,
        step_result: Dict[str, Any],
        execution_time_ms: int,
        output_data: Optional[Dict[str, Any]] = None,
    ) -> WorkflowExecutionStepCompletedEvent:
        """Create a WorkflowExecutionStepCompletedEvent."""
        return WorkflowExecutionStepCompletedEvent(
            event_id=uuid4(),
            workflow_id=workflow_id,
            execution_id=execution_id,
            created_at=datetime.now(),
            version=1,  # Will be updated when stored
            step_name=step_name,
            step_result=step_result,
            execution_time_ms=execution_time_ms,
            output_data=output_data,
        )

    def create_workflow_completed_event(
        self,
        workflow_id: str,
        execution_id: str,
        final_result: Dict[str, Any],
        total_processing_time_ms: int,
        output_summary: Dict[str, Any],
        steps_completed: int,
    ) -> WorkflowExecutionCompletedEvent:
        """Create a WorkflowExecutionCompletedEvent."""
        return WorkflowExecutionCompletedEvent(
            event_id=uuid4(),
            workflow_id=workflow_id,
            execution_id=execution_id,
            created_at=datetime.now(UTC),
            version=1,  # Will be updated when stored
            final_result=final_result,
            total_processing_time_ms=total_processing_time_ms,
            output_summary=output_summary,
            steps_completed=steps_completed,
        )

    def create_workflow_failed_event(
        self,
        workflow_id: str,
        execution_id: str,
        error_type: str,
        error_message: str,
        failed_step: Optional[str] = None,
        retry_count: int = 0,
    ) -> WorkflowExecutionFailedEvent:
        """Create a WorkflowExecutionFailedEvent."""
        return WorkflowExecutionFailedEvent(
            event_id=uuid4(),
            workflow_id=workflow_id,
            execution_id=execution_id,
            created_at=datetime.now(UTC),
            version=1,  # Will be updated when stored
            error_type=error_type,
            error_message=error_message,
            failed_step=failed_step,
            retry_count=retry_count,
        )

    # High-level workflow event orchestration methods

    async def emit_workflow_started(
        self,
        workflow_id: str,
        execution_id: str,
        file_info: FileInfo,
        metadata: Dict[str, Any],
    ) -> EventStoreRecord:
        """Emit and store a workflow started event."""
        event = self.create_workflow_started_event(
            workflow_id=workflow_id,
            execution_id=execution_id,
            file_info=file_info,
            metadata=metadata,
        )
        return await self.store_event(event)

    async def emit_step_completed(
        self,
        workflow_id: str,
        execution_id: str,
        step_name: str,
        step_result: Dict[str, Any],
        execution_time_ms: int,
        output_data: Optional[Dict[str, Any]] = None,
    ) -> EventStoreRecord:
        """Emit and store a step completed event."""
        event = self.create_step_completed_event(
            workflow_id=workflow_id,
            execution_id=execution_id,
            step_name=step_name,
            step_result=step_result,
            execution_time_ms=execution_time_ms,
            output_data=output_data,
        )
        return await self.store_event(event)

    async def emit_workflow_completed(
        self,
        workflow_id: str,
        execution_id: str,
        final_result: Dict[str, Any],
        total_processing_time_ms: int,
        output_summary: Dict[str, Any],
        steps_completed: int,
    ) -> EventStoreRecord:
        """Emit and store a workflow completed event."""
        event = self.create_workflow_completed_event(
            workflow_id=workflow_id,
            execution_id=execution_id,
            final_result=final_result,
            total_processing_time_ms=total_processing_time_ms,
            output_summary=output_summary,
            steps_completed=steps_completed,
        )
        return await self.store_event(event)

    async def emit_workflow_failed(
        self,
        workflow_id: str,
        execution_id: str,
        error_type: str,
        error_message: str,
        failed_step: Optional[str] = None,
        retry_count: int = 0,
    ) -> EventStoreRecord:
        """Emit and store a workflow failed event."""
        event = self.create_workflow_failed_event(
            workflow_id=workflow_id,
            execution_id=execution_id,
            error_type=error_type,
            error_message=error_message,
            failed_step=failed_step,
            retry_count=retry_count,
        )
        return await self.store_event(event)
