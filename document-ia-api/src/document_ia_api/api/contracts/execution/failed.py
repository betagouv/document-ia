from typing import Literal, Optional

from pydantic import BaseModel, NonNegativeInt

from document_ia_api.api.contracts.execution.types import ExecutionStatus


class ExecutionFailedData(BaseModel):
    error_type: str
    failed_step: Optional[str]
    retry_count: NonNegativeInt
    workflow_id: str
    error_message: str


class ExecutionFailedModel(BaseModel):
    id: str
    status: Literal[ExecutionStatus.FAILED]
    data: ExecutionFailedData
