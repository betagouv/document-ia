from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union, Optional

from pydantic import BaseModel, Field, HttpUrl


class ExecutionStartedData(BaseModel):
    created_at: datetime
    file_name: str
    content_type: str
    presigned_url: HttpUrl | str


class ExecutionDoneResult(BaseModel):
    document_type: str
    confidence: float
    explanation: str


class ExecutionSuccessData(BaseModel):
    total_processing_time_ms: int
    result: ExecutionDoneResult


class ExecutionFailedData(BaseModel):
    error_type: str
    failed_step: Optional[str]
    retry_count: int
    workflow_id: str
    error_message: str


class ExecutionStartedModel(BaseModel):
    id: str
    status: Literal["STARTED"]
    data: ExecutionStartedData


class ExecutionSuccessModel(BaseModel):
    id: str
    status: Literal["SUCCESS"]
    data: ExecutionSuccessData


class ExecutionFailedModel(BaseModel):
    id: str
    status: Literal["FAILED"]
    data: ExecutionFailedData


# Discriminated union on "status"
ExecutionResponse = Annotated[
    Union[ExecutionStartedModel, ExecutionSuccessModel, ExecutionFailedModel],
    Field(discriminator="status"),
]
