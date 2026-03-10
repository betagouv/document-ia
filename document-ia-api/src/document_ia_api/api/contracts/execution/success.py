from typing import Literal, TypeVar, Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from document_ia_api.api.contracts.execution.result import (
    ClassificationResult,
    ExtractionResult,
)
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_infra.data.event.schema.barcode import BarcodeVariant

T = TypeVar("T")


class SuccessResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    classification: Optional[ClassificationResult] = Field(default=None)
    extraction: Optional[ExtractionResult] = Field(default=None)
    barcodes: list[BarcodeVariant] = Field(default=[])
    workflow_metadata: Optional[list[Any]] = Field(default=None)


class SuccessData(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    total_processing_time_ms: int
    result: SuccessResult


class ExecutionSuccessModel(BaseModel):
    id: str
    status: Literal[ExecutionStatus.SUCCESS]
    data: SuccessData
