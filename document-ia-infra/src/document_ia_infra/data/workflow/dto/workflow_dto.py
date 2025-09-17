from dataclasses import dataclass
from typing import List


@dataclass
class WorkflowDTO:
    id: str
    name: str
    description: str
    version: str
    enabled: bool
    supported_file_types: List[str]
    steps: List[str]
    max_file_size_mb: int
    processing_timeout_minutes: int
    created_at: str
    updated_at: str
