from datetime import datetime
from typing import Literal

from pydantic import BaseModel, HttpUrl

from document_ia_api.api.contracts.execution.types import ExecutionStatus


class ExecutionStartedData(BaseModel):
    created_at: datetime
    file_name: str
    content_type: str
    presigned_url: HttpUrl | str


class ExecutionStartedModel(BaseModel):
    id: str
    status: Literal[ExecutionStatus.STARTED]
    data: ExecutionStartedData
