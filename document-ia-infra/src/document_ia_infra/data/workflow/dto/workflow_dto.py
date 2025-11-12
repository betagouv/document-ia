from enum import Enum
from typing import List

from pydantic import BaseModel


class LLMModel(str, Enum):
    ALBERT_LARGE = "albert-large"
    ALBERT_SMALL = "albert-small"


class WorkflowDTO(BaseModel):
    id: str
    name: str
    description: str
    version: str
    enabled: bool
    supported_file_types: List[str]
    steps: List[str]
    llm_model: LLMModel
    max_file_size_mb: int
    processing_timeout_minutes: int
    created_at: str
    updated_at: str
