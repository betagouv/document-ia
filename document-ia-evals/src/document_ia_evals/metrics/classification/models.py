"""Models for classification metric observations."""

from typing import Optional
from pydantic import BaseModel


class ClassificationObservation(BaseModel):
    """Observation for a single classification task."""

    score: float  # 1.0 for match, 0.0 for mismatch
    expected_type: str
    predicted_type: str
    match: bool
    error: Optional[str] = None
