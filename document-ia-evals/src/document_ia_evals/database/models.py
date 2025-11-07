"""SQLAlchemy models for experiment tracking - Privacy-first design."""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Experiment(Base):
    """
    Experiment run tracking.
    
    Privacy: Only stores references to Label Studio (project_id) and metric results.
    NO sensitive data from Label Studio is stored here.
    """
    __tablename__ = "experiments"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    
    # Reference to Label Studio (just the ID, not the data)
    label_studio_project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Metric information
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    # Experiment statistics
    total_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Status: 'running', 'completed', 'failed'
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='running')
    
    # Optional notes or metadata
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationships
    observations: Mapped[List["Observation"]] = relationship(
        "Observation",
        back_populates="experiment",
        cascade="all, delete-orphan",
        lazy="select"
    )
    
    # Indexes
    __table_args__ = (
        Index('ix_experiments_project_metric', 'label_studio_project_id', 'metric_name', 'created_at'),
        Index('ix_experiments_created_at', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return (
            f"<Experiment(id={self.id}, "
            f"project_id={self.label_studio_project_id}, "
            f"metric={self.metric_name}, "
            f"score={self.average_score:.3f if self.average_score else 'N/A'}, "
            f"status={self.status})>"
        )
    
    @property
    def success_rate(self) -> float:
        """Calculate the success rate (processed / total tasks)."""
        if self.total_tasks == 0:
            return 0.0
        return self.processed_count / self.total_tasks
    
    @property
    def skipped_count(self) -> int:
        """Calculate number of skipped tasks."""
        return self.total_tasks - self.processed_count


class Observation(Base):
    """
    Individual task evaluation result - PRIVACY FIRST.
    
    Stores:
    - References to Label Studio (task_id, prediction_id) - NOT the data itself
    - Metric computation results (scores, field_scores) - Safe to store
    - Model version for tracking
    
    Does NOT store:
    - Raw predictions
    - Ground truth data
    - Task input data
    - Any sensitive information
    """
    __tablename__ = "observations"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    
    # Foreign key to experiment
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False
    )
    
    # References to Label Studio (IDs only - can fetch data on demand)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    prediction_id: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Model version from Label Studio prediction
    model_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Metric results (PRIVACY-SAFE: only scores and computed results)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    
    # Detailed metric results in JSONB format
    # Example: {"field_scores": {"name": 0.95, "email": 1.0}, "error": null}
    # NO raw data stored - only computation results
    metric_results: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    # Relationships
    experiment: Mapped["Experiment"] = relationship(
        "Experiment",
        back_populates="observations"
    )
    
    # Indexes
    __table_args__ = (
        Index('ix_observations_experiment', 'experiment_id'),
        Index('ix_observations_task', 'task_id'),
        Index('ix_observations_model_version', 'model_version'),
    )
    
    def __repr__(self) -> str:
        return (
            f"<Observation(id={self.id}, "
            f"task_id={self.task_id}, "
            f"prediction_id={self.prediction_id}, "
            f"score={self.score:.3f}, "
            f"model={self.model_version})>"
        )
    
    def get_field_scores(self) -> dict:
        """Extract field scores from metric_results."""
        if self.metric_results and 'field_scores' in self.metric_results:
            return self.metric_results['field_scores']
        return {}
    
    def has_error(self) -> bool:
        """Check if this observation has an error."""
        if self.metric_results and 'error' in self.metric_results:
            return self.metric_results['error'] is not None
        return False
    
    def get_error(self) -> Optional[str]:
        """Get error message if present."""
        if self.metric_results and 'error' in self.metric_results:
            return self.metric_results['error']
        return None