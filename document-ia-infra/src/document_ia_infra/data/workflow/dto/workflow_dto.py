from enum import Enum
from typing import List

from pydantic import BaseModel


class WorkflowType(str, Enum):
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"


class WorkflowDTO(BaseModel):
    id: str
    name: str
    description: str
    version: str
    enabled: bool
    supported_file_types: List[str]
    steps: List[str]
    type: WorkflowType
    llm_model: str
    max_file_size_mb: int
    processing_timeout_minutes: int
    created_at: str
    updated_at: str
