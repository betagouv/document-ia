from typing import Union, Literal, TypeVar, Generic, Any, Optional

from pydantic import BaseModel, ConfigDict

from document_ia_api.api.contracts.execution.result import (
    ClassificationResult,
    ExtractionResult,
)
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_infra.core.model.types.secret import SecretPayloadDict
from document_ia_infra.data.workflow.dto.workflow_dto import WorkflowType

T = TypeVar("T")


class SuccessData(BaseModel, Generic[T]):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    workflow_type: WorkflowType
    total_processing_time_ms: int
    result: T
    extracted_barcodes: Optional[SecretPayloadDict[Any]]


class ClassificationSuccessData(SuccessData[ClassificationResult]):
    workflow_type: WorkflowType = WorkflowType.CLASSIFICATION


class ExtractionSuccessData(SuccessData[ExtractionResult]):
    workflow_type: WorkflowType = WorkflowType.EXTRACTION


class ExecutionSuccessModel(BaseModel):
    id: str
    status: Literal[ExecutionStatus.SUCCESS]
    data: Union[ExtractionSuccessData, ClassificationSuccessData]
