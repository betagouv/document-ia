from typing import Literal, TypeVar, Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from document_ia_api.api.contracts.execution.result import ClassificationResult
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_infra.core.model.types.secret import SecretPayloadDict

T = TypeVar("T")


class SuccessResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    classification_result: Optional[ClassificationResult] = Field(default=None)
    extraction_result: Optional[SecretPayloadDict[Any]] = Field(default=None)
    extracted_barcodes: Optional[SecretPayloadDict[Any]] = Field(default=None)
    workflow_metadata: Optional[list[Any]] = Field(default=None)


class SuccessData(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    total_processing_time_ms: int
    result: SuccessResult


class ExecutionSuccessModel(BaseModel):
    id: str
    status: Literal[ExecutionStatus.SUCCESS]
    data: SuccessData
