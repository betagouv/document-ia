"""Data models for json_schema_extra metric."""

from typing import Dict, Any, Optional
from pydantic import BaseModel


class JsonSchemaExtraObservation(BaseModel):
    """Data model for json_schema_extra metric observations."""
    
    score: float
    document_type: Optional[str] = None
    model_type: Optional[str] = None
    field_scores: Dict[str, Dict[str, float]] = {}
    field_details: Dict[str, Dict[str, Any]] = {}
    evaluated_fields: int = 0
    skipped_fields: int = 0
    error: Optional[str] = None
