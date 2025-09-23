from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, HttpUrl


class ExecutionPendingData(BaseModel):
    created_at: datetime
    file_name: str
    content_type: str
    presigned_url: HttpUrl | str


class ExecutionDoneResult(BaseModel):
    document_type: str
    confidence: float
    explanation: str


class ExecutionDoneData(BaseModel):
    total_processing_time_ms: int
    result: ExecutionDoneResult


class ExecutionPendingModel(BaseModel):
    id: str
    status: Literal["PENDING"]
    data: ExecutionPendingData


class ExecutionDoneModel(BaseModel):
    id: str
    status: Literal["DONE"]
    data: ExecutionDoneData


# Discriminated union on "status"
ExecutionResponse = Annotated[
    Union[ExecutionPendingModel, ExecutionDoneModel],
    Field(discriminator="status"),
]
