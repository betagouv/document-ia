from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from document_ia_infra.data.workflow.dto.workflow_dto import WorkflowType
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_api.api.contracts.execution.result import (
    ClassificationResult,
    ExtractionResult,
)


class ClassificationSuccessData(BaseModel):
    workflow_type: Literal[WorkflowType.CLASSIFICATION]
    total_processing_time_ms: int
    result: ClassificationResult


class ExtractionSuccessData(BaseModel):
    workflow_type: Literal[WorkflowType.EXTRACTION]
    total_processing_time_ms: int
    result: ExtractionResult


class ExecutionSuccessModel(BaseModel):
    id: str
    status: Literal[ExecutionStatus.SUCCESS]
    # Discriminated union for success data by workflow type
    data: Annotated[
        Union[ExtractionSuccessData, ClassificationSuccessData],
        Field(discriminator="workflow_type"),
    ]
