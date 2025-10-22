from datetime import datetime

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
    start_time: datetime
    steps_metadata: list[StepMetadata] = Field(default=[])
    number_of_step_executed: int = Field(default=0)
