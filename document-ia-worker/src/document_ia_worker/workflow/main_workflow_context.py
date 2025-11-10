from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class StepMetadata(BaseModel):
    step_name: str
    execution_time: float


class StepLLMMetadata(StepMetadata):
    request_tokens: int
    response_tokens: int
    execution_time: float = Field(default=0)


class MainWorkflowContext(BaseModel):
    execution_id: str
    organization_id: Optional[UUID]
    start_time: datetime
    steps_metadata: list[StepMetadata] = Field(default=[])
    number_of_step_executed: int = Field(default=0)
