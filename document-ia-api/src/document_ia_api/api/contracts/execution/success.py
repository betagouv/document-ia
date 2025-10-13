from typing import Union, Literal, TypeVar, Generic

from pydantic import BaseModel

from document_ia_api.api.contracts.execution.result import (
    ClassificationResult,
    ExtractionResult,
)
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_infra.data.workflow.dto.workflow_dto import WorkflowType

T = TypeVar("T")


class SuccessData(BaseModel, Generic[T]):
    workflow_type: WorkflowType
    total_processing_time_ms: int
    result: T


class ClassificationSuccessData(SuccessData[ClassificationResult]):
    workflow_type: WorkflowType = WorkflowType.CLASSIFICATION


class ExtractionSuccessData(SuccessData[ExtractionResult]):
    workflow_type: WorkflowType = WorkflowType.EXTRACTION


class ExecutionSuccessModel(BaseModel):
    id: str
    status: Literal[ExecutionStatus.SUCCESS]
    data: Union[ExtractionSuccessData, ClassificationSuccessData]
