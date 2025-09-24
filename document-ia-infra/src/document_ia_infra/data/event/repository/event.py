"""
Event store repository for database operations.

This module implements the repository pattern for event store operations,
providing async CRUD operations and event stream reconstruction.
"""

import logging
from typing import List, Optional, Dict, Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.entity.event_entity import EventEntity
from document_ia_infra.exception.retryable_exception import RetryableException

logger = logging.getLogger(__name__)


class EventRepository:
    """Repository for event store database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def put_event(
        self,
        workflow_id: str,
        execution_id: str,
        event_type: str,
        event_data: Dict[str, Any],
    ) -> EventDTO:
        """
        Store an event in the event store.

        Args:
            workflow_id: Workflow identifier
            execution_id: Execution instance identifier
            event_type: Type of event
            event_data: Event payload data

        Returns:
            EventStoreRecord: The stored event record

        Raises:
            IntegrityError: If event with same version already exists
        """
        try:
            event_record = EventEntity(
                workflow_id=workflow_id,
                execution_id=execution_id,
                event_type=event_type,
                event=event_data,
            )

            self.session.add(event_record)
            await self.session.flush()  # Flush to get the ID
            await self.session.refresh(event_record)

            logger.debug(
                f"Event stored: {event_type} for execution {execution_id} "
                f"(workflow: {workflow_id})"
            )

            return EventDTO(
                id=event_record.id,
                workflow_id=event_record.workflow_id,
                execution_id=event_record.execution_id,
                created_at=event_record.created_at,
                event_type=EventType.from_str(event_record.event_type),
                event=event_record.event,
            )

        except IntegrityError as e:
            logger.error(
                f"Failed to store event {event_type} for execution {execution_id}: {e}"
            )
            await self.session.rollback()
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error storing event {event_type} for execution {execution_id}: {e}"
            )
            await self.session.rollback()
            raise

    async def get_created_event_if_execution_not_completed_or_failed(
        self,
        execution_id: str,
    ) -> Optional[EventDTO]:
        """
        Retrieve the latest event for a specific execution ID.

        Args:
            execution_id: Execution instance identifier

        Returns:
            Optional[EventStoreRecord]: The latest event or None if not found
        """
        query = (
            select(EventEntity)
            .where(EventEntity.execution_id == execution_id)
            .order_by(EventEntity.created_at.desc())
        )

        try:
            results = await self.session.execute(query)
            events = results.scalars().all()
            event: Optional[EventEntity] = None

            last_event = events[-1]
            # If last_event for an execution is Completed return None no need to reexecute the process
            if last_event.event_type == EventType.WORKFLOW_EXECUTION_COMPLETED:
                event = None
            # Otherwise if the last event is a started event we need to process.
            elif last_event.event_type == EventType.WORKFLOW_EXECUTION_STARTED:
                event = last_event
            # The complicated case :
            # If the last event is a failed but the error is retryable we need to find the WORKFLOW_EXECUTION_STARTED event
            elif (
                last_event.event_type == EventType.WORKFLOW_EXECUTION_FAILED
                and last_event.event.get("error_type") == RetryableException.__name__
            ):
                for e in reversed(events):
                    if e.event_type == EventType.WORKFLOW_EXECUTION_STARTED:
                        event = e
                        break

            if event:
                return EventDTO(
                    id=event.id,
                    workflow_id=event.workflow_id,
                    execution_id=event.execution_id,
                    created_at=event.created_at,
                    event_type=EventType.from_str(event.event_type),
                    event=event.event,
                )
            return None

        except OSError as e:
            logger.error("Database connection error: {e}")
            raise RetryableException(e)
        except Exception as e:
            logger.error(
                f"Unexpected error retrieving last event for execution {execution_id}: {e}"
            )
            await self.session.rollback()
            raise

    async def get_last_event_by_execution_id(
        self,
        execution_id: str,
    ) -> Optional[EventDTO]:
        """
        Retrieve the latest event for a specific execution ID.

        Args:
            execution_id: Execution instance identifier

        Returns:
            Optional[EventStoreRecord]: The latest event or None if not found
        """
        query = (
            select(EventEntity)
            .where(EventEntity.execution_id == execution_id)
            .order_by(EventEntity.created_at.desc())
            .limit(1)
        )

        try:
            result = await self.session.execute(query)
            event = result.scalars().first()

            if event:
                return EventDTO(
                    id=event.id,
                    workflow_id=event.workflow_id,
                    execution_id=event.execution_id,
                    created_at=event.created_at,
                    event_type=EventType.from_str(event.event_type),
                    event=event.event,
                )
            return None

        except OSError as e:
            logger.error("Database connection error: {e}")
            raise RetryableException(e)
        except Exception as e:
            logger.error(
                f"Unexpected error retrieving last event for execution {execution_id}: {e}"
            )
            await self.session.rollback()
            raise

    async def get_events_by_execution_id(
        self,
        execution_id: str,
        workflow_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[EventDTO]:
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
        query = select(EventEntity).where(EventEntity.execution_id == execution_id)

        if workflow_id:
            query = query.where(EventEntity.workflow_id == workflow_id)

        query = query.order_by(EventEntity.created_at.asc())

        if offset > 0:
            query = query.offset(offset)

        if limit:
            query = query.limit(limit)

        result = await self.session.execute(query)
        events = result.scalars().all()

        return [
            EventDTO(
                id=event.id,
                workflow_id=event.workflow_id,
                execution_id=event.execution_id,
                created_at=event.created_at,
                event_type=EventType.from_str(event.event_type),
                event=event.event,
            )
            for event in events
        ]
