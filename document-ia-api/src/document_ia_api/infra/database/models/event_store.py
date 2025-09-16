"""
SQLAlchemy model for event store table.

This module defines the database model for storing events in the event store,
following event sourcing principles.
"""

from datetime import datetime
from typing import Dict, Any
from uuid import UUID, uuid4

from sqlalchemy import String, DateTime, Integer, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from document_ia_api.infra.database.database import Base


class EventStore(Base):
    """
    Event store table for storing workflow execution events.

    This table implements event sourcing by storing all state changes
    as immutable events with versioning support.
    """

    __tablename__ = "event_store"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
        comment="Unique identifier for the event",
    )

    # Event metadata
    workflow_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="Workflow identifier"
    )

    execution_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="Execution instance identifier"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        index=True,
        comment="Event timestamp",
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Type of event (e.g., WorkflowExecutionStarted)",
    )

    # Event payload stored as JSONB for efficient querying
    event: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, comment="Event payload as JSON"
    )

    # Version for optimistic locking
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Event version for optimistic locking",
    )

    # TODO: add constraint
    # UNIQUE CONSTRAINT (workflow_id, execution_id, event_type, version)

    # Composite indexes for efficient querying
    __table_args__ = (
        # Index for querying events by execution_id and workflow_id
        Index(
            "idx_event_store_execution_workflow",
            "execution_id",
            "workflow_id",
            "created_at",
        ),
        # Index for querying events by execution_id and version
        Index("idx_event_store_execution_version", "execution_id", "version"),
        # Index for time-based queries
        Index("idx_event_store_created_at", "created_at"),
        # UNIQUE CONSTRAINT (workflow_id, execution_id, event_type, version)
        UniqueConstraint("workflow_id", "execution_id", "event_type", "version"),
    )

    def __repr__(self) -> str:
        return (
            f"<EventStore(id={self.id}, "
            f"workflow_id={self.workflow_id}, "
            f"execution_id={self.execution_id}, "
            f"event_type={self.event_type}, "
            f"version={self.version})>"
        )

    def to_dict(self) -> dict[str, Any]:  # type: ignore[override]
        """Convert the model instance to a dictionary."""
        return {
            "id": str(self.id),
            "workflow_id": self.workflow_id,
            "execution_id": self.execution_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "event_type": self.event_type,
            "event": self.event,
            "version": self.version,
        }
