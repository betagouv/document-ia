"""Data models for classification accuracy metric."""

from typing import Optional
from pydantic import BaseModel


class ClassificationAccuracyObservation(BaseModel):
    """Data model for classification accuracy metric observations."""

    score: float
    expected: str
    predicted: str
    error: Optional[str] = None
