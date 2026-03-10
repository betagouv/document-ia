from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import (
    ClassificationParameters,
    ExtractionParameters,
)


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
    classification_parameters: Optional[ClassificationParameters] = Field(default=None)
    extraction_parameters: Optional[ExtractionParameters] = Field(default=None)
    steps_metadata: list[StepMetadata] = Field(default=[])
    number_of_step_executed: int = Field(default=0)
