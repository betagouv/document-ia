"""
Event store repository for database operations.

This module implements the repository pattern for event store operations,
providing async CRUD operations and event stream reconstruction.
"""

import logging
from typing import List, Optional, Dict, Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from infra.database.models.event_store import EventStore
from schemas.events import EventStoreRecord

logger = logging.getLogger(__name__)


class EventStoreRepository:
    """Repository for event store database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def put_event(
        self,
        workflow_id: str,
        execution_id: str,
        event_type: str,
        event_data: Dict[str, Any],
        version: int = 1,
    ) -> EventStoreRecord:
        """
        Store an event in the event store.

        Args:
            workflow_id: Workflow identifier
            execution_id: Execution instance identifier
            event_type: Type of event
            event_data: Event payload data
            version: Event version for optimistic locking

        Returns:
            EventStoreRecord: The stored event record

        Raises:
            IntegrityError: If event with same version already exists
        """
        try:
            event_record = EventStore(
                workflow_id=workflow_id,
                execution_id=execution_id,
                event_type=event_type,
                event=event_data,
                version=version,
            )

            self.session.add(event_record)
            await self.session.flush()  # Flush to get the ID
            await self.session.refresh(event_record)

            logger.debug(
                f"Event stored: {event_type} for execution {execution_id} "
                f"(workflow: {workflow_id}, version: {version})"
            )

            return EventStoreRecord(
                id=event_record.id,
                workflow_id=event_record.workflow_id,
                execution_id=event_record.execution_id,
                created_at=event_record.created_at,
                event_type=event_record.event_type,
                event=event_record.event,
                version=event_record.version,
            )

        except IntegrityError as e:
            logger.error(
                f"Failed to store event {event_type} for execution {execution_id}: {e}"
            )
            await self.session.rollback()
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
        query = select(EventStore).where(EventStore.execution_id == execution_id)

        if workflow_id:
            query = query.where(EventStore.workflow_id == workflow_id)

        query = query.order_by(EventStore.created_at.asc(), EventStore.version.asc())

        if offset > 0:
            query = query.offset(offset)

        if limit:
            query = query.limit(limit)

        result = await self.session.execute(query)
        events = result.scalars().all()

        return [
            EventStoreRecord(
                id=event.id,
                workflow_id=event.workflow_id,
                execution_id=event.execution_id,
                created_at=event.created_at,
                event_type=event.event_type,
                event=event.event,
                version=event.version,
            )
            for event in events
        ]

    async def get_latest_event_version(
        self, execution_id: str, workflow_id: Optional[str] = None
    ) -> int:
        """
        Get the latest event version for an execution.

        Args:
            execution_id: Execution instance identifier
            workflow_id: Optional workflow identifier for additional filtering

        Returns:
            int: Latest version number, 0 if no events exist
        """
        query = select(func.max(EventStore.version)).where(
            EventStore.execution_id == execution_id
        )

        if workflow_id:
            query = query.where(EventStore.workflow_id == workflow_id)

        result = await self.session.execute(query)
        max_version = result.scalar()

        return max_version or 0
